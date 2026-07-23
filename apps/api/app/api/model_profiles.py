import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import SecretBox
from app.database import get_session
from app.model_identity import model_snapshot
from app.models import BenchmarkRun, ModelProfile, RunStatus, UserAccount, UserModelAccess, UserRole
from app.schemas import ModelCreate, ModelRead, ModelUpdate
from app.security import can_access_model, csrf_protection, current_user

router = APIRouter(prefix="/models", tags=["models"])


def to_read(profile: ModelProfile) -> ModelRead:
    return ModelRead(
        id=profile.id,
        name=profile.name,
        provider=profile.provider,
        base_url=profile.base_url,
        model_id=profile.model_id,
        has_api_key=bool(profile.encrypted_api_key),
        native_tools=profile.native_tools,
        parameters=profile.parameters,
        enabled=profile.enabled,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("", response_model=list[ModelRead])
def list_models(
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[ModelRead]:
    statement = select(ModelProfile).where(ModelProfile.archived_at.is_(None))
    if user.role != UserRole.admin:
        statement = statement.join(
            UserModelAccess,
            UserModelAccess.model_profile_id == ModelProfile.id,
        ).where(UserModelAccess.user_id == user.id)
    profiles = session.scalars(statement.order_by(ModelProfile.name)).all()
    return [to_read(profile) for profile in profiles]


@router.post("", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: ModelCreate,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> ModelRead:
    box = SecretBox(get_settings().app_secret)
    duplicate = session.scalar(
        select(ModelProfile.id)
        .join(UserModelAccess, UserModelAccess.model_profile_id == ModelProfile.id)
        .where(
            UserModelAccess.user_id == user.id,
            ModelProfile.name == payload.name,
            ModelProfile.archived_at.is_(None),
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="You already have a model profile with this name")
    profile = ModelProfile(
        name=payload.name,
        provider=payload.provider,
        base_url=str(payload.base_url).rstrip("/"),
        model_id=payload.model_id,
        encrypted_api_key=box.encrypt(payload.api_key),
        native_tools=payload.native_tools,
        parameters=payload.parameters,
        enabled=payload.enabled,
    )
    session.add(profile)
    try:
        session.flush()
        session.add(UserModelAccess(user_id=user.id, model_profile_id=profile.id))
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Could not create model profile") from exc
    session.refresh(profile)
    return to_read(profile)


@router.patch("/{model_id}", response_model=ModelRead)
def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> ModelRead:
    profile = session.scalar(
        select(ModelProfile).where(ModelProfile.id == model_id).with_for_update()
    )
    if not can_access_model(session, user, profile) or profile.archived_at is not None:
        raise HTTPException(status_code=404, detail="Model profile not found")
    assert profile is not None

    if payload.name is not None and payload.name != profile.name:
        duplicate = session.scalar(
            select(ModelProfile.id)
            .join(
                UserModelAccess,
                UserModelAccess.model_profile_id == ModelProfile.id,
            )
            .where(
                UserModelAccess.user_id == user.id,
                ModelProfile.name == payload.name,
                ModelProfile.id != profile.id,
                ModelProfile.archived_at.is_(None),
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="You already have a model profile with this name",
            )

    if payload.name is not None:
        profile.name = payload.name
    if payload.provider is not None:
        profile.provider = payload.provider
    if payload.base_url is not None:
        profile.base_url = str(payload.base_url).rstrip("/")
    if payload.model_id is not None:
        profile.model_id = payload.model_id
    if payload.native_tools is not None:
        profile.native_tools = payload.native_tools
    if payload.parameters is not None:
        profile.parameters = payload.parameters
    if payload.enabled is not None:
        profile.enabled = payload.enabled
    if "api_key" in payload.model_fields_set:
        profile.encrypted_api_key = SecretBox(get_settings().app_secret).encrypt(payload.api_key)

    session.commit()
    session.refresh(profile)
    return to_read(profile)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(
    model_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> None:
    profile = session.scalar(
        select(ModelProfile).where(ModelProfile.id == model_id).with_for_update()
    )
    if not can_access_model(session, user, profile) or profile.archived_at is not None:
        raise HTTPException(status_code=404, detail="Model profile not found")
    assert profile is not None

    active_statuses = (
        RunStatus.queued,
        RunStatus.preparing,
        RunStatus.running,
        RunStatus.scoring,
    )
    active_runs = (
        session.scalar(
            select(func.count(BenchmarkRun.id)).where(
                or_(
                    BenchmarkRun.candidate_model_id == model_id,
                    BenchmarkRun.judge_model_id == model_id,
                ),
                BenchmarkRun.status.in_(active_statuses),
            )
        )
        or 0
    )
    if active_runs:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Model profile is used by {active_runs} active run(s). "
                "Cancel or finish them before deleting it."
            ),
        )

    snapshot = model_snapshot(profile)
    referenced_runs = session.scalars(
        select(BenchmarkRun).where(
            or_(
                BenchmarkRun.candidate_model_id == model_id,
                BenchmarkRun.judge_model_id == model_id,
            )
        )
    ).all()
    for run in referenced_runs:
        config = dict(run.config or {})
        if (
            run.candidate_model_id == model_id
            and not _valid_model_snapshot(config.get("candidate_model_snapshot"))
        ):
            config["candidate_model_snapshot"] = snapshot
        if (
            run.judge_model_id == model_id
            and not _valid_model_snapshot(config.get("judge_model_snapshot"))
        ):
            config["judge_model_snapshot"] = snapshot
        run.config = config

    profile.enabled = False
    profile.encrypted_api_key = None
    profile.base_url = "https://archived.invalid"
    profile.native_tools = False
    profile.parameters = {}
    profile.archived_at = datetime.now(UTC)
    session.commit()


def _valid_model_snapshot(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(field), str) and bool(value[field])
        for field in ("profile_id", "name", "provider", "model_id")
    )

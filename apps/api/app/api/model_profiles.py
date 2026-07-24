import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.credentials import (
    CredentialError,
    create_api_key_payload,
    encode_payload,
    validate_credential_compatibility,
)
from app.database import get_session
from app.model_identity import model_snapshot
from app.models import (
    BenchmarkRun,
    CredentialKind,
    CredentialStatus,
    ModelProfile,
    ModelProvider,
    ProviderCredential,
    RunStatus,
    UserAccount,
    UserModelAccess,
    UserRole,
)
from app.schemas import ModelCreate, ModelRead, ModelUpdate
from app.security import can_access_model, csrf_protection, current_user

router = APIRouter(prefix="/models", tags=["models"])


def to_read(session: Session, profile: ModelProfile) -> ModelRead:
    credential = (
        session.get(ProviderCredential, profile.credential_id)
        if profile.credential_id
        else None
    )
    return ModelRead(
        id=profile.id,
        name=profile.name,
        provider=profile.provider,
        base_url=profile.base_url,
        model_id=profile.model_id,
        has_api_key=bool(profile.encrypted_api_key or credential),
        credential_id=credential.id if credential else None,
        credential_name=credential.name if credential else None,
        credential_kind=credential.kind if credential else None,
        credential_status=credential.status if credential else None,
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
    return [to_read(session, profile) for profile in profiles]


@router.post("", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: ModelCreate,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> ModelRead:
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
    credential = None
    if payload.credential_id is not None:
        credential = owned_credential(session, user.id, payload.credential_id)
    elif payload.api_key:
        credential = create_inline_credential(
            session,
            owner_id=user.id,
            profile_name=payload.name,
            secret=payload.api_key,
        )
    if credential is not None:
        ensure_compatible(payload.provider, credential.kind)
    if payload.provider in {ModelProvider.codex, ModelProvider.gemini} and credential is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "credential_required",
                "message": f"{payload.provider.value} profiles require a compatible credential",
            },
        )
    profile = ModelProfile(
        name=payload.name,
        provider=payload.provider,
        base_url=str(payload.base_url).rstrip("/"),
        model_id=payload.model_id,
        encrypted_api_key=None,
        credential_id=credential.id if credential else None,
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
    return to_read(session, profile)


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
    effective_provider = payload.provider or profile.provider
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
    if "credential_id" in payload.model_fields_set:
        if payload.credential_id is None:
            profile.credential_id = None
        elif payload.credential_id == profile.credential_id:
            credential = session.get(ProviderCredential, payload.credential_id)
            if credential is None or credential.archived_at is not None:
                raise HTTPException(status_code=422, detail="Credential is unavailable")
            ensure_compatible(effective_provider, credential.kind)
        else:
            credential = owned_credential(session, user.id, payload.credential_id)
            ensure_compatible(effective_provider, credential.kind)
            profile.credential_id = credential.id
            profile.encrypted_api_key = None
    if "api_key" in payload.model_fields_set:
        if payload.api_key:
            credential = create_inline_credential(
                session,
                owner_id=user.id,
                profile_name=payload.name or profile.name,
                secret=payload.api_key,
            )
            profile.credential_id = credential.id
            profile.encrypted_api_key = None
        else:
            profile.credential_id = None
            profile.encrypted_api_key = None

    if profile.credential_id is not None:
        current_credential = session.get(ProviderCredential, profile.credential_id)
        if current_credential is None or current_credential.archived_at is not None:
            raise HTTPException(status_code=422, detail="Credential is unavailable")
        ensure_compatible(profile.provider, current_credential.kind)
    elif profile.provider in {ModelProvider.codex, ModelProvider.gemini}:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "credential_required",
                "message": f"{profile.provider.value} profiles require a compatible credential",
            },
        )

    session.commit()
    session.refresh(profile)
    return to_read(session, profile)


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
    profile.credential_id = None
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


def owned_credential(
    session: Session,
    owner_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> ProviderCredential:
    credential = session.scalar(
        select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.owner_id == owner_id,
            ProviderCredential.archived_at.is_(None),
        )
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential


def ensure_compatible(
    provider: ModelProvider,
    kind: CredentialKind,
) -> None:
    try:
        validate_credential_compatibility(provider, kind)
    except CredentialError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


def create_inline_credential(
    session: Session,
    *,
    owner_id: uuid.UUID,
    profile_name: str,
    secret: str,
) -> ProviderCredential:
    base_name = f"{profile_name.strip()} · API key"
    name = base_name
    suffix = 2
    while session.scalar(
        select(ProviderCredential.id).where(
            ProviderCredential.owner_id == owner_id,
            ProviderCredential.name == name,
            ProviderCredential.archived_at.is_(None),
        )
    ):
        name = f"{base_name} {suffix}"
        suffix += 1
    credential = ProviderCredential(
        owner_id=owner_id,
        name=name,
        kind=CredentialKind.api_key,
        encrypted_payload=encode_payload(create_api_key_payload(secret)),
        status=CredentialStatus.ready,
        last_validated_at=datetime.now(UTC),
    )
    session.add(credential)
    session.flush()
    return credential

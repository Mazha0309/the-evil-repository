import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import SecretBox
from app.database import get_session
from app.models import ModelProfile, UserAccount, UserModelAccess, UserRole
from app.schemas import ModelCreate, ModelRead
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
    statement = select(ModelProfile)
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


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(
    model_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> None:
    profile = session.get(ModelProfile, model_id)
    if not can_access_model(session, user, profile):
        raise HTTPException(status_code=404, detail="Model profile not found")
    session.delete(profile)
    session.commit()

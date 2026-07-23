import hmac
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.models import LoginFailure, UserAccount, UserRole, UserSession
from app.platform import ensure_platform_settings
from app.schemas import (
    AccountUpdate,
    AuthConfig,
    AuthRead,
    LoginCreate,
    RegisterCreate,
    SessionRead,
    SetupCreate,
    UserRead,
)
from app.security import (
    clear_session_cookie,
    csrf_protection,
    current_user,
    hash_password,
    issue_session,
    normalize_username,
    secret_digest,
    session_id,
    set_session_cookie,
    validate_password,
    verify_password,
)
from app.version import VERSION

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfig)
def auth_config(session: Session = Depends(get_session)) -> AuthConfig:
    platform = ensure_platform_settings(session)
    user_count = session.scalar(select(func.count(UserAccount.id))) or 0
    session.commit()
    return AuthConfig(
        setup_required=user_count == 0,
        registration_enabled=platform.registration_enabled and user_count > 0,
        setup_token_required=bool(get_settings().setup_token),
        version=VERSION,
    )


@router.post("/setup", response_model=AuthRead, status_code=status.HTTP_201_CREATED)
def setup_admin(
    payload: SetupCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> AuthRead:
    if session.scalar(select(func.count(UserAccount.id))):
        raise HTTPException(status_code=409, detail="Initial setup has already been completed")
    required_token = get_settings().setup_token
    if required_token and not hmac.compare_digest(payload.setup_token or "", required_token):
        raise HTTPException(status_code=403, detail="Invalid setup token")
    user = create_user(
        session,
        username=payload.username,
        password=payload.password,
        role=UserRole.admin,
        enabled=True,
    )
    ensure_platform_settings(session)
    issued = issue_session(session, user, request)
    user.last_login_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, issued)
    return AuthRead(user=UserRead.model_validate(user), csrf_token=issued.csrf_token, expires_at=issued.expires_at)


@router.post("/register", response_model=AuthRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> AuthRead:
    platform = ensure_platform_settings(session)
    if not session.scalar(select(func.count(UserAccount.id))):
        raise HTTPException(status_code=409, detail="Initial setup is required")
    if not platform.registration_enabled:
        raise HTTPException(status_code=403, detail="Registration is disabled")
    user = create_user(
        session,
        username=payload.username,
        password=payload.password,
        role=UserRole.user,
        enabled=True,
    )
    issued = issue_session(session, user, request)
    user.last_login_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, issued)
    return AuthRead(user=UserRead.model_validate(user), csrf_token=issued.csrf_token, expires_at=issued.expires_at)


@router.post("/login", response_model=AuthRead)
def login(
    payload: LoginCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> AuthRead:
    try:
        username = normalize_username(payload.username)
    except ValueError:
        username = ""
    client_address = request.client.host if request.client else "unknown"
    fingerprint = secret_digest(f"{username}|{client_address}")
    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    session.execute(delete(LoginFailure).where(LoginFailure.occurred_at < datetime.now(UTC) - timedelta(days=1)))
    failures = (
        session.scalar(
            select(func.count(LoginFailure.id)).where(
                LoginFailure.fingerprint == fingerprint,
                LoginFailure.occurred_at >= cutoff,
            )
        )
        or 0
    )
    if failures >= 5:
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    user = session.scalar(select(UserAccount).where(UserAccount.username == username))
    if not user or not verify_password(payload.password, user.password_hash):
        session.add(LoginFailure(fingerprint=fingerprint))
        session.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.enabled:
        raise HTTPException(status_code=403, detail="Account is disabled")
    issued = issue_session(session, user, request)
    session.execute(delete(LoginFailure).where(LoginFailure.fingerprint == fingerprint))
    user.last_login_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, issued)
    return AuthRead(user=UserRead.model_validate(user), csrf_token=issued.csrf_token, expires_at=issued.expires_at)


@router.get("/me", response_model=AuthRead)
def me(
    request: Request,
    user: UserAccount = Depends(current_user),
) -> AuthRead:
    auth_session: UserSession = request.state.auth_session
    return AuthRead(
        user=UserRead.model_validate(user),
        csrf_token=auth_session.csrf_token,
        expires_at=auth_session.expires_at,
    )


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: AccountUpdate,
    request: Request,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> UserAccount:
    if payload.username is not None:
        change_username(session, user, payload.username)
    if payload.new_password is not None:
        if not payload.current_password or not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user.password_hash = hash_password(payload.new_password)
        current = session_id(request)
        for item in session.scalars(
            select(UserSession).where(UserSession.user_id == user.id, UserSession.id != current)
        ).all():
            session.delete(item)
    session.commit()
    session.refresh(user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    _: UserAccount = Depends(csrf_protection),
) -> None:
    auth_session: UserSession = request.state.auth_session
    session.delete(auth_session)
    session.commit()
    clear_session_cookie(response)


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    request: Request,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[SessionRead]:
    current = session_id(request)
    items = session.scalars(
        select(UserSession).where(UserSession.user_id == user.id).order_by(UserSession.last_seen_at.desc())
    ).all()
    return [
        SessionRead(
            id=item.id,
            expires_at=item.expires_at,
            user_agent=item.user_agent,
            ip_address=item.ip_address,
            created_at=item.created_at,
            last_seen_at=item.last_seen_at,
            current=item.id == current,
        )
        for item in items
    ]


@router.delete("/sessions/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    target_id: uuid.UUID,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> None:
    target = session.get(UserSession, target_id)
    if not target or target.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    is_current = target.id == session_id(request)
    session.delete(target)
    session.commit()
    if is_current:
        clear_session_cookie(response)


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: UserRole,
    enabled: bool,
) -> UserAccount:
    try:
        normalized_username = normalize_username(username)
        validate_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if session.scalar(select(UserAccount.id).where(UserAccount.username == normalized_username)):
        raise HTTPException(status_code=409, detail="An account with this username already exists")
    user = UserAccount(
        username=normalized_username,
        password_hash=hash_password(password),
        role=role,
        enabled=enabled,
    )
    session.add(user)
    session.flush()
    return user


def change_username(session: Session, user: UserAccount, username: str) -> None:
    try:
        normalized_username = normalize_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = session.scalar(
        select(UserAccount.id).where(
            UserAccount.username == normalized_username,
            UserAccount.id != user.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="An account with this username already exists")
    user.username = normalized_username

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.models import (
    BenchmarkRun,
    ModelProfile,
    UserAccount,
    UserModelAccess,
    UserRole,
    UserRunAccess,
    UserSession,
)

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    expires_at: datetime


def normalize_username(value: str) -> str:
    username = value.strip().casefold()
    if not 2 <= len(username) <= 32 or not all(character.isalnum() or character in "._-" for character in username):
        raise ValueError(
            "Username must be 2-32 characters and contain only letters, numbers, dots, hyphens, or underscores"
        )
    return username


def validate_password(value: str) -> str:
    if len(value) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if len(value) > 256:
        raise ValueError("Password is too long")
    return value


def hash_password(password: str) -> str:
    validate_password(password)
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(derived).decode(),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, expected_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode())
        expected = base64.urlsafe_b64decode(expected_value.encode())
        actual = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def secret_digest(value: str) -> str:
    return hmac.new(
        get_settings().app_secret.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def issue_session(session: Session, user: UserAccount, request: Request) -> IssuedSession:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=secret_digest(token),
            csrf_token=csrf_token,
            expires_at=expires_at,
            user_agent=(request.headers.get("user-agent") or "")[:500] or None,
            ip_address=request.client.host[:80] if request.client else None,
        )
    )
    return IssuedSession(token=token, csrf_token=csrf_token, expires_at=expires_at)


def set_session_cookie(response: Response, issued: IssuedSession) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        issued.token,
        expires=issued.expires_at,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> UserAccount:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    auth_session = session.scalar(select(UserSession).where(UserSession.token_hash == secret_digest(token)))
    now = datetime.now(UTC)
    if not auth_session or aware(auth_session.expires_at) <= now:
        if auth_session:
            session.delete(auth_session)
            session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = session.get(UserAccount, auth_session.user_id)
    if not user or not user.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    if aware(auth_session.last_seen_at) <= now - SESSION_TOUCH_INTERVAL:
        auth_session.last_seen_at = now
        session.commit()
    request.state.auth_session = auth_session
    return user


def admin_user(user: UserAccount = Depends(current_user)) -> UserAccount:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


def csrf_protection(
    request: Request,
    user: UserAccount = Depends(current_user),
) -> UserAccount:
    csrf_token = request.headers.get("x-csrf-token")
    auth_session: UserSession = request.state.auth_session
    if not csrf_token or not hmac.compare_digest(csrf_token, auth_session.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return user


def admin_csrf(
    user: UserAccount = Depends(csrf_protection),
) -> UserAccount:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


def can_access_model(session: Session, user: UserAccount, model: ModelProfile | None) -> bool:
    if model is None:
        return False
    if user.role == UserRole.admin:
        return True
    return (
        session.get(
            UserModelAccess,
            {"user_id": user.id, "model_profile_id": model.id},
        )
        is not None
    )


def can_access_run(session: Session, user: UserAccount, run: BenchmarkRun | None) -> bool:
    if run is None:
        return False
    if user.role == UserRole.admin:
        return True
    return session.get(UserRunAccess, {"user_id": user.id, "run_id": run.id}) is not None


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def session_id(request: Request) -> uuid.UUID:
    auth_session: UserSession = request.state.auth_session
    return auth_session.id

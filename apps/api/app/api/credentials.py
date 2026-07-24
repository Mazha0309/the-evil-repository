import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.credentials import (
    CredentialError,
    create_anthropic_oauth_payload,
    create_api_key_payload,
    encode_payload,
    normalize_import,
    poll_codex_device_flow,
    resolve_credential,
    start_codex_device_flow,
)
from app.database import get_session
from app.model_discovery import sync_credential_models
from app.models import (
    CredentialKind,
    CredentialStatus,
    ModelProfile,
    ProviderCredential,
    UserAccount,
)
from app.schemas import (
    CredentialCreate,
    CredentialImport,
    CredentialModelSyncRead,
    CredentialRead,
    CredentialUpdate,
    OAuthDevicePoll,
    OAuthDevicePollResult,
    OAuthDeviceStart,
    SyncedModelRead,
)
from app.security import csrf_protection, current_user

router = APIRouter(prefix="/credentials", tags=["credentials"])


def to_read(
    session: Session,
    credential: ProviderCredential,
) -> CredentialRead:
    model_count = (
        session.scalar(
            select(func.count(ModelProfile.id)).where(
                ModelProfile.credential_id == credential.id,
                ModelProfile.archived_at.is_(None),
            )
        )
        or 0
    )
    return CredentialRead(
        id=credential.id,
        name=credential.name,
        kind=credential.kind,
        account_hint=credential.account_hint,
        status=credential.status,
        expires_at=credential.expires_at,
        last_refreshed_at=credential.last_refreshed_at,
        last_validated_at=credential.last_validated_at,
        last_error_code=credential.last_error_code,
        model_count=model_count,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.get("", response_model=list[CredentialRead])
def list_credentials(
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[CredentialRead]:
    credentials = session.scalars(
        select(ProviderCredential)
        .where(
            ProviderCredential.owner_id == user.id,
            ProviderCredential.archived_at.is_(None),
        )
        .order_by(ProviderCredential.name, ProviderCredential.created_at)
    ).all()
    return [to_read(session, credential) for credential in credentials]


@router.post(
    "",
    response_model=CredentialRead,
    status_code=status.HTTP_201_CREATED,
)
def create_credential(
    payload: CredentialCreate,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> CredentialRead:
    if payload.kind not in {
        CredentialKind.api_key,
        CredentialKind.anthropic_oauth,
    }:
        raise HTTPException(
            status_code=422,
            detail=(
                "Codex and Gemini OAuth credentials must use JSON import "
                "or an interactive login"
            ),
        )
    ensure_unique_name(session, user.id, payload.name)
    if payload.kind == CredentialKind.anthropic_oauth:
        encrypted_payload = encode_payload(
            create_anthropic_oauth_payload(payload.secret)
        )
        account_hint = "Claude subscription"
    else:
        encrypted_payload = encode_payload(create_api_key_payload(payload.secret))
        account_hint = None
    credential = ProviderCredential(
        owner_id=user.id,
        name=payload.name.strip(),
        kind=payload.kind,
        encrypted_payload=encrypted_payload,
        account_hint=account_hint,
        status=CredentialStatus.ready,
        last_validated_at=datetime.now(UTC),
    )
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return to_read(session, credential)


@router.post(
    "/import",
    response_model=CredentialRead,
    status_code=status.HTTP_201_CREATED,
)
def import_credential(
    payload: CredentialImport,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> CredentialRead:
    ensure_unique_name(session, user.id, payload.name)
    try:
        normalized, hint, expires_at = normalize_import(
            payload.kind,
            payload.document,
        )
    except CredentialError as exc:
        raise credential_http_error(exc) from exc
    credential = ProviderCredential(
        owner_id=user.id,
        name=payload.name.strip(),
        kind=payload.kind,
        encrypted_payload=encode_payload(normalized),
        account_hint=hint,
        status=CredentialStatus.unchecked,
        expires_at=expires_at,
    )
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return to_read(session, credential)


@router.patch("/{credential_id}", response_model=CredentialRead)
def update_credential(
    credential_id: uuid.UUID,
    payload: CredentialUpdate,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> CredentialRead:
    credential = owned_credential(session, user.id, credential_id, lock=True)
    if payload.name is not None and payload.name.strip() != credential.name:
        ensure_unique_name(
            session,
            user.id,
            payload.name,
            exclude_id=credential.id,
        )
        credential.name = payload.name.strip()
    if payload.secret is not None:
        if credential.kind == CredentialKind.api_key:
            normalized = create_api_key_payload(payload.secret)
            credential.account_hint = None
        elif credential.kind == CredentialKind.anthropic_oauth:
            normalized = create_anthropic_oauth_payload(payload.secret)
            credential.account_hint = "Claude subscription"
        else:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "credential_secret_update_unsupported",
                    "message": (
                        "This OAuth credential must be re-imported or "
                        "authenticated again"
                    ),
                },
            )
        credential.encrypted_payload = encode_payload(normalized)
        credential.status = CredentialStatus.ready
        credential.expires_at = None
        credential.last_error_code = None
        credential.last_validated_at = datetime.now(UTC)
    session.commit()
    session.refresh(credential)
    return to_read(session, credential)


@router.post("/{credential_id}/refresh", response_model=CredentialRead)
def refresh_credential(
    credential_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> CredentialRead:
    credential = owned_credential(session, user.id, credential_id, lock=True)
    if (
        credential.kind == CredentialKind.anthropic_oauth
        and credential.status == CredentialStatus.needs_reauth
    ):
        raise credential_http_error(
            CredentialError(
                "anthropic_oauth_replace_required",
                "Generate a new token with `claude setup-token` and replace "
                "the saved credential",
            )
        )
    if credential.kind in {
        CredentialKind.api_key,
        CredentialKind.anthropic_oauth,
    }:
        try:
            resolve_credential(session, credential, force_refresh=False)
        except CredentialError as exc:
            session.commit()
            raise credential_http_error(exc) from exc
        credential.status = CredentialStatus.ready
        credential.last_validated_at = datetime.now(UTC)
        credential.last_error_code = None
    else:
        try:
            resolve_credential(
                session,
                credential,
                # A refresh token may be single-use and rotating. Verify the
                # current access token first and only refresh near expiry.
                force_refresh=False,
            )
        except CredentialError as exc:
            session.commit()
            raise credential_http_error(exc) from exc
    session.commit()
    session.refresh(credential)
    return to_read(session, credential)


@router.post(
    "/{credential_id}/models/sync",
    response_model=CredentialModelSyncRead,
)
def sync_models(
    credential_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> CredentialModelSyncRead:
    credential = owned_credential(session, user.id, credential_id, lock=True)
    try:
        result = sync_credential_models(
            session,
            credential,
            user.id,
        )
    except CredentialError as exc:
        session.commit()
        raise credential_http_error(exc) from exc
    response = CredentialModelSyncRead(
        credential_id=result.credential_id,
        provider=result.provider,
        discovered=result.discovered,
        created=result.created,
        existing=result.existing,
        models=[
            SyncedModelRead(
                id=item.profile.id,
                name=item.profile.name,
                provider=item.profile.provider,
                model_id=item.profile.model_id,
                created=item.created,
            )
            for item in result.models
        ],
    )
    session.commit()
    return response


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_credential(
    credential_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> None:
    credential = owned_credential(session, user.id, credential_id, lock=True)
    references = (
        session.scalar(
            select(func.count(ModelProfile.id)).where(
                ModelProfile.credential_id == credential.id,
                ModelProfile.archived_at.is_(None),
            )
        )
        or 0
    )
    if references:
        raise HTTPException(
            status_code=409,
            detail=(f"Credential is used by {references} model profile(s). Detach those profiles before deleting it."),
        )
    credential.encrypted_payload = encode_payload({"deleted": True})
    credential.account_hint = None
    credential.status = CredentialStatus.error
    credential.last_error_code = "credential_deleted"
    credential.archived_at = datetime.now(UTC)
    session.commit()


@router.post(
    "/oauth/codex/device/start",
    response_model=OAuthDeviceStart,
)
def start_codex_oauth(
    user: UserAccount = Depends(csrf_protection),
) -> OAuthDeviceStart:
    try:
        return OAuthDeviceStart.model_validate(start_codex_device_flow(user.id))
    except CredentialError as exc:
        raise credential_http_error(exc) from exc


@router.post(
    "/oauth/codex/device/poll",
    response_model=OAuthDevicePollResult,
)
def poll_codex_oauth(
    payload: OAuthDevicePoll,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> OAuthDevicePollResult:
    ensure_unique_name(session, user.id, payload.name)
    try:
        state, normalized, hint, expires_at = poll_codex_device_flow(
            user.id,
            payload.flow_token,
        )
    except CredentialError as exc:
        raise credential_http_error(exc) from exc
    if state != "complete" or normalized is None:
        return OAuthDevicePollResult(state=state)

    now = datetime.now(UTC)
    credential = ProviderCredential(
        owner_id=user.id,
        name=payload.name.strip(),
        kind=CredentialKind.codex_oauth,
        encrypted_payload=encode_payload(normalized),
        account_hint=hint,
        status=CredentialStatus.ready,
        expires_at=expires_at,
        last_refreshed_at=now,
        last_validated_at=now,
    )
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return OAuthDevicePollResult(
        state="complete",
        credential=to_read(session, credential),
    )


def owned_credential(
    session: Session,
    owner_id: uuid.UUID,
    credential_id: uuid.UUID,
    *,
    lock: bool,
) -> ProviderCredential:
    statement = select(ProviderCredential).where(
        ProviderCredential.id == credential_id,
        ProviderCredential.owner_id == owner_id,
        ProviderCredential.archived_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    credential = session.scalar(statement)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential


def ensure_unique_name(
    session: Session,
    owner_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    clean = name.strip()
    statement = select(ProviderCredential.id).where(
        ProviderCredential.owner_id == owner_id,
        ProviderCredential.name == clean,
        ProviderCredential.archived_at.is_(None),
    )
    if exclude_id is not None:
        statement = statement.where(ProviderCredential.id != exclude_id)
    if session.scalar(statement):
        raise HTTPException(
            status_code=409,
            detail="You already have a credential with this name",
        )


def credential_http_error(exc: CredentialError) -> HTTPException:
    status_code = 422
    if "unreachable" in exc.code or "transport" in exc.code:
        status_code = 503
    elif (
        "rejected" in exc.code
        or "denied" in exc.code
        or exc.code
        in {
            "invalid_grant",
            "refresh_token_expired",
            "refresh_token_invalidated",
            "refresh_token_reused",
        }
    ):
        status_code = 401
    elif "owner_mismatch" in exc.code:
        status_code = 403
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )

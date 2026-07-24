import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import SecretBox
from app.database import SessionLocal
from app.models import (
    CredentialKind,
    CredentialStatus,
    ModelProfile,
    ModelProvider,
    ProviderCredential,
)

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_DEVICE_START_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
CODEX_DEVICE_POLL_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
CODEX_DEVICE_VERIFY_URL = "https://auth.openai.com/codex/device"
CODEX_DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"

GEMINI_TOKEN_URL = "https://oauth2.googleapis.com/token"
GEMINI_CODE_ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal"

MAX_IMPORT_BYTES = 65_536
TOKEN_REFRESH_WINDOW = timedelta(minutes=5)
OAUTH_TIMEOUT_SECONDS = 20


class CredentialError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedCredential:
    kind: CredentialKind
    token: str
    account_id: str | None = None
    project_id: str | None = None


class CredentialResolver:
    """Resolve a model credential without exposing its payload to the Runner."""

    def __init__(self, profile_id: uuid.UUID) -> None:
        self.profile_id = profile_id

    def __call__(self, *, force_refresh: bool = False) -> ResolvedCredential | None:
        return resolve_model_credential(
            self.profile_id,
            force_refresh=force_refresh,
        )


def encode_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    encrypted = SecretBox(get_settings().app_secret).encrypt(encoded)
    if encrypted is None:
        raise CredentialError("credential_empty", "Credential payload is empty")
    return encrypted


def decode_payload(credential: ProviderCredential) -> dict[str, Any]:
    try:
        encoded = SecretBox(get_settings().app_secret).decrypt(
            credential.encrypted_payload
        )
        payload = json.loads(encoded or "")
    except Exception as exc:
        raise CredentialError(
            "credential_decrypt_failed",
            "The saved credential cannot be decrypted with the current APP_SECRET",
        ) from exc
    if not isinstance(payload, dict):
        raise CredentialError(
            "credential_payload_invalid",
            "The saved credential payload is not a JSON object",
        )
    return payload


def normalize_import(
    kind: CredentialKind,
    document: dict[str, Any],
) -> tuple[dict[str, Any], str | None, datetime | None]:
    _validate_document_size(document)
    if kind == CredentialKind.codex_oauth:
        return normalize_codex_auth_document(document)
    if kind == CredentialKind.gemini_oauth:
        return normalize_gemini_auth_document(document)
    raise CredentialError(
        "credential_import_kind_invalid",
        "API keys must be entered as a secret rather than imported as JSON",
    )


def normalize_codex_auth_document(
    document: dict[str, Any],
) -> tuple[dict[str, Any], str | None, datetime | None]:
    token_container = document.get("tokens")
    tokens = token_container if isinstance(token_container, dict) else document
    access_token = _optional_string(tokens.get("access_token"))
    refresh_token = _optional_string(tokens.get("refresh_token"))
    id_token = _optional_string(tokens.get("id_token"))
    supplied_account_id = _optional_string(
        tokens.get("account_id") or document.get("account_id")
    )
    if not refresh_token:
        raise CredentialError(
            "codex_refresh_token_missing",
            "Codex auth.json does not contain tokens.refresh_token",
        )

    claimed_account_id = (
        extract_codex_account_id(id_token)
        or extract_codex_account_id(access_token)
    )
    if (
        supplied_account_id
        and claimed_account_id
        and supplied_account_id != claimed_account_id
    ):
        raise CredentialError(
            "codex_account_mismatch",
            "Codex auth.json account_id does not match its token claims",
        )
    account_id = supplied_account_id or claimed_account_id
    if not account_id:
        raise CredentialError(
            "codex_account_missing",
            "Codex auth.json does not identify a ChatGPT account",
        )

    email = extract_jwt_string(id_token, "email")
    expires_at = jwt_expiry(access_token)
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "account_id": account_id,
        "last_refresh": _optional_string(document.get("last_refresh")),
    }
    return payload, email or mask_identifier(account_id), expires_at


def normalize_gemini_auth_document(
    document: dict[str, Any],
) -> tuple[dict[str, Any], str | None, datetime | None]:
    access_token = _optional_string(document.get("access_token"))
    refresh_token = _optional_string(document.get("refresh_token"))
    if not refresh_token:
        raise CredentialError(
            "gemini_refresh_token_missing",
            "Gemini oauth_creds.json does not contain refresh_token",
        )
    expires_at = parse_gemini_expiry(document.get("expiry_date"))
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": _optional_string(document.get("token_type")) or "Bearer",
        "scope": _optional_string(document.get("scope")),
        "expiry_date": (
            int(expires_at.timestamp() * 1000) if expires_at is not None else None
        ),
        "project_id": _optional_string(
            document.get("project_id")
            or document.get("quota_project_id")
            or document.get("cloudaicompanionProject")
        ),
    }
    hint = _optional_string(document.get("email"))
    return payload, hint, expires_at


def resolve_model_credential(
    profile_id: uuid.UUID,
    *,
    force_refresh: bool = False,
) -> ResolvedCredential | None:
    with SessionLocal() as session:
        profile = session.get(ModelProfile, profile_id)
        if profile is None or profile.archived_at is not None:
            raise CredentialError(
                "model_profile_unavailable",
                "The model profile is unavailable",
            )
        if profile.credential_id is None:
            legacy = SecretBox(get_settings().app_secret).decrypt(
                profile.encrypted_api_key
            )
            if legacy:
                return ResolvedCredential(
                    kind=CredentialKind.api_key,
                    token=legacy,
                )
            return None

        credential = session.scalar(
            select(ProviderCredential)
            .where(
                ProviderCredential.id == profile.credential_id,
                ProviderCredential.archived_at.is_(None),
            )
            .with_for_update()
        )
        if credential is None:
            raise CredentialError(
                "credential_unavailable",
                "The model profile references a missing credential",
            )
        validate_credential_compatibility(profile.provider, credential.kind)
        try:
            resolved = resolve_credential(
                session,
                credential,
                force_refresh=force_refresh,
            )
        except CredentialError:
            session.commit()
            raise
        session.commit()
        return resolved


def resolve_credential(
    session: Session,
    credential: ProviderCredential,
    *,
    force_refresh: bool = False,
    client: httpx.Client | None = None,
) -> ResolvedCredential:
    payload = decode_payload(credential)
    if credential.kind == CredentialKind.api_key:
        secret = _optional_string(payload.get("secret"))
        if not secret:
            raise CredentialError(
                "api_key_missing",
                "The saved API key is empty",
            )
        credential.status = CredentialStatus.ready
        credential.last_error_code = None
        return ResolvedCredential(kind=credential.kind, token=secret)

    if force_refresh or credential_needs_refresh(credential, payload):
        payload = refresh_oauth_credential(
            credential,
            payload,
            client=client,
        )
        session.flush()

    token = _optional_string(payload.get("access_token"))
    if not token:
        raise CredentialError(
            "oauth_access_token_missing",
            "The OAuth credential has no usable access token",
        )

    if credential.kind == CredentialKind.codex_oauth:
        account_id = _optional_string(payload.get("account_id"))
        if not account_id:
            raise CredentialError(
                "codex_account_missing",
                "The Codex OAuth credential has no ChatGPT account id",
            )
        credential.status = CredentialStatus.ready
        credential.last_validated_at = datetime.now(UTC)
        credential.last_error_code = None
        return ResolvedCredential(
            kind=credential.kind,
            token=token,
            account_id=account_id,
        )

    project_id = _optional_string(payload.get("project_id"))
    if not project_id:
        project_id = discover_gemini_project(token, client=client)
        payload["project_id"] = project_id
        credential.encrypted_payload = encode_payload(payload)
        credential.last_validated_at = datetime.now(UTC)
        credential.status = CredentialStatus.ready
        credential.last_error_code = None
    else:
        credential.last_validated_at = datetime.now(UTC)
        credential.status = CredentialStatus.ready
        credential.last_error_code = None
    return ResolvedCredential(
        kind=credential.kind,
        token=token,
        project_id=project_id,
    )


def credential_needs_refresh(
    credential: ProviderCredential,
    payload: dict[str, Any],
) -> bool:
    if not _optional_string(payload.get("access_token")):
        return True
    expires_at = credential.expires_at
    if expires_at is None:
        expires_at = jwt_expiry(_optional_string(payload.get("access_token")))
    elif expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at is None or expires_at <= datetime.now(UTC) + TOKEN_REFRESH_WINDOW


def refresh_oauth_credential(
    credential: ProviderCredential,
    payload: dict[str, Any],
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    refresh_token = _optional_string(payload.get("refresh_token"))
    if not refresh_token:
        _mark_credential_error(
            credential,
            CredentialStatus.needs_reauth,
            "oauth_refresh_token_missing",
        )
        raise CredentialError(
            "oauth_refresh_token_missing",
            "The OAuth credential must be imported or authenticated again",
        )

    owns_client = client is None
    http = client or httpx.Client(timeout=OAUTH_TIMEOUT_SECONDS)
    try:
        if credential.kind == CredentialKind.codex_oauth:
            form = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_CLIENT_ID,
            }
            response = http.post(
                CODEX_TOKEN_URL,
                data=form,
                headers={"Accept": "application/json"},
            )
        elif credential.kind == CredentialKind.gemini_oauth:
            client_id, client_secret = gemini_oauth_client_credentials()
            form = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            }
            response = http.post(
                GEMINI_TOKEN_URL,
                data=form,
                headers={"Accept": "application/json"},
            )
        else:
            raise CredentialError(
                "credential_refresh_unsupported",
                "This credential kind does not support OAuth refresh",
            )
    except httpx.TransportError as exc:
        _mark_credential_error(
            credential,
            CredentialStatus.error,
            "oauth_refresh_transport_error",
        )
        raise CredentialError(
            "oauth_refresh_transport_error",
            "The OAuth token service could not be reached",
        ) from exc
    finally:
        if owns_client:
            http.close()

    if response.status_code in {401, 403}:
        _mark_credential_error(
            credential,
            CredentialStatus.needs_reauth,
            "oauth_refresh_rejected",
        )
        raise CredentialError(
            "oauth_refresh_rejected",
            "The OAuth refresh token was rejected; authenticate again",
        )
    if not 200 <= response.status_code < 300:
        _mark_credential_error(
            credential,
            CredentialStatus.error,
            f"oauth_refresh_http_{response.status_code}",
        )
        raise CredentialError(
            f"oauth_refresh_http_{response.status_code}",
            f"The OAuth token service returned HTTP {response.status_code}",
        )

    try:
        body = response.json()
    except ValueError as exc:
        _mark_credential_error(
            credential,
            CredentialStatus.error,
            "oauth_refresh_response_invalid",
        )
        raise CredentialError(
            "oauth_refresh_response_invalid",
            "The OAuth token service returned invalid JSON",
        ) from exc
    access_token = _optional_string(body.get("access_token"))
    if not access_token:
        _mark_credential_error(
            credential,
            CredentialStatus.error,
            "oauth_refresh_access_token_missing",
        )
        raise CredentialError(
            "oauth_refresh_access_token_missing",
            "The OAuth token service did not return an access token",
        )

    now = datetime.now(UTC)
    payload["access_token"] = access_token
    payload["refresh_token"] = (
        _optional_string(body.get("refresh_token")) or refresh_token
    )
    if credential.kind == CredentialKind.codex_oauth:
        payload["id_token"] = (
            _optional_string(body.get("id_token"))
            or _optional_string(payload.get("id_token"))
        )
        payload["account_id"] = (
            _optional_string(payload.get("account_id"))
            or extract_codex_account_id(payload.get("id_token"))
            or extract_codex_account_id(access_token)
        )
        payload["last_refresh"] = now.isoformat()
    expires_in = body.get("expires_in")
    expires_at = (
        now + timedelta(seconds=int(expires_in))
        if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool)
        else jwt_expiry(access_token)
    )
    if credential.kind == CredentialKind.gemini_oauth and expires_at is not None:
        payload["expiry_date"] = int(expires_at.timestamp() * 1000)

    credential.encrypted_payload = encode_payload(payload)
    credential.expires_at = expires_at
    credential.last_refreshed_at = now
    credential.last_validated_at = now
    credential.status = CredentialStatus.ready
    credential.last_error_code = None
    return payload


def discover_gemini_project(
    access_token: str,
    *,
    client: httpx.Client | None = None,
) -> str:
    owns_client = client is None
    http = client or httpx.Client(timeout=OAUTH_TIMEOUT_SECONDS)
    try:
        response = http.post(
            f"{GEMINI_CODE_ASSIST_URL}:loadCodeAssist",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "metadata": {
                    "ideType": "IDE_UNSPECIFIED",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI",
                }
            },
        )
    except httpx.TransportError as exc:
        raise CredentialError(
            "gemini_code_assist_unreachable",
            "Gemini Code Assist could not be reached",
        ) from exc
    finally:
        if owns_client:
            http.close()
    if response.status_code in {401, 403}:
        raise CredentialError(
            "gemini_oauth_rejected",
            "Gemini rejected the imported OAuth credential",
        )
    if not 200 <= response.status_code < 300:
        raise CredentialError(
            f"gemini_code_assist_http_{response.status_code}",
            f"Gemini Code Assist returned HTTP {response.status_code}",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise CredentialError(
            "gemini_code_assist_response_invalid",
            "Gemini Code Assist returned invalid JSON",
        ) from exc
    project_id = _optional_string(body.get("cloudaicompanionProject"))
    if project_id:
        return project_id
    raise CredentialError(
        "gemini_onboarding_required",
        "Open Gemini CLI once to complete account onboarding, then reimport oauth_creds.json",
    )


def validate_credential_compatibility(
    provider: ModelProvider,
    kind: CredentialKind,
) -> None:
    if provider == ModelProvider.codex and kind != CredentialKind.codex_oauth:
        raise CredentialError(
            "credential_kind_mismatch",
            "Codex subscription profiles require a Codex OAuth credential",
        )
    if provider == ModelProvider.gemini and kind not in {
        CredentialKind.api_key,
        CredentialKind.gemini_oauth,
    }:
        raise CredentialError(
            "credential_kind_mismatch",
            "Gemini profiles require an API key or Gemini OAuth credential",
        )
    if provider not in {ModelProvider.codex, ModelProvider.gemini} and kind != CredentialKind.api_key:
        raise CredentialError(
            "credential_kind_mismatch",
            "This Provider protocol requires an API key credential",
        )


def start_codex_device_flow(
    owner_id: uuid.UUID,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    http = client or httpx.Client(timeout=OAUTH_TIMEOUT_SECONDS)
    try:
        response = http.post(
            CODEX_DEVICE_START_URL,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "evil-repository-auth/0.11",
            },
            json={"client_id": CODEX_CLIENT_ID},
        )
    except httpx.TransportError as exc:
        raise CredentialError(
            "codex_device_flow_unreachable",
            "OpenAI device authentication could not be reached",
        ) from exc
    finally:
        if owns_client:
            http.close()
    if not 200 <= response.status_code < 300:
        raise CredentialError(
            f"codex_device_flow_http_{response.status_code}",
            f"OpenAI device authentication returned HTTP {response.status_code}",
        )
    try:
        body = response.json()
        device_auth_id = str(body["device_auth_id"])
        user_code = str(body["user_code"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CredentialError(
            "codex_device_flow_response_invalid",
            "OpenAI device authentication returned an invalid response",
        ) from exc
    interval = _bounded_int(body.get("interval"), default=5, minimum=1, maximum=30)
    expires_in = _bounded_int(
        body.get("expires_in"),
        default=900,
        minimum=60,
        maximum=1800,
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    flow_token = encode_payload(
        {
            "owner_id": str(owner_id),
            "device_auth_id": device_auth_id,
            "user_code": user_code,
            "expires_at": expires_at.isoformat(),
        }
    )
    return {
        "expires_at": expires_at,
        "flow_token": flow_token,
        "interval": interval,
        "user_code": user_code,
        "verification_uri": CODEX_DEVICE_VERIFY_URL,
    }


def poll_codex_device_flow(
    owner_id: uuid.UUID,
    flow_token: str,
    *,
    client: httpx.Client | None = None,
) -> tuple[str, dict[str, Any] | None, str | None, datetime | None]:
    flow = _decode_flow_token(flow_token)
    if flow.get("owner_id") != str(owner_id):
        raise CredentialError(
            "codex_device_flow_owner_mismatch",
            "This device login belongs to another account",
        )
    expires_at = _parse_datetime(flow.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now(UTC):
        raise CredentialError(
            "codex_device_flow_expired",
            "The Codex device login has expired",
        )

    owns_client = client is None
    http = client or httpx.Client(timeout=OAUTH_TIMEOUT_SECONDS)
    try:
        response = http.post(
            CODEX_DEVICE_POLL_URL,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "evil-repository-auth/0.11",
            },
            json={
                "device_auth_id": flow["device_auth_id"],
                "user_code": flow["user_code"],
            },
        )
        if response.status_code in {400, 403, 404, 409, 425, 428}:
            error_code = _oauth_error_code(response)
            if error_code in {
                "authorization_pending",
                "pending",
                "slow_down",
                "unknown",
            }:
                return "pending", None, None, None
            if error_code in {"access_denied", "authorization_declined"}:
                raise CredentialError(
                    "codex_device_flow_denied",
                    "The Codex device login was denied",
                )
        if not 200 <= response.status_code < 300:
            raise CredentialError(
                f"codex_device_poll_http_{response.status_code}",
                f"OpenAI device authentication returned HTTP {response.status_code}",
            )
        poll_body = response.json()
        authorization_code = str(poll_body["authorization_code"])
        code_verifier = str(poll_body["code_verifier"])
        token_response = http.post(
            CODEX_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "evil-repository-auth/0.11",
            },
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": CODEX_DEVICE_REDIRECT_URI,
                "client_id": CODEX_CLIENT_ID,
                "code_verifier": code_verifier,
            },
        )
    except CredentialError:
        raise
    except (httpx.TransportError, KeyError, TypeError, ValueError) as exc:
        raise CredentialError(
            "codex_device_poll_failed",
            "The Codex device login could not be completed",
        ) from exc
    finally:
        if owns_client:
            http.close()

    if not 200 <= token_response.status_code < 300:
        raise CredentialError(
            f"codex_token_exchange_http_{token_response.status_code}",
            f"OpenAI token exchange returned HTTP {token_response.status_code}",
        )
    try:
        token_body = token_response.json()
    except ValueError as exc:
        raise CredentialError(
            "codex_token_exchange_invalid",
            "OpenAI token exchange returned invalid JSON",
        ) from exc
    payload, hint, token_expires_at = normalize_codex_auth_document(token_body)
    return "complete", payload, hint, token_expires_at


def gemini_oauth_client_credentials() -> tuple[str, str]:
    settings = get_settings()
    client_id = (settings.gemini_oauth_client_id or "").strip()
    client_secret = (settings.gemini_oauth_client_secret or "").strip()
    if not client_id or not client_secret:
        raise CredentialError(
            "gemini_oauth_client_not_configured",
            "Gemini OAuth refresh requires GEMINI_OAUTH_CLIENT_ID and "
            "GEMINI_OAUTH_CLIENT_SECRET on both the API and Runner",
        )
    return client_id, client_secret


def create_api_key_payload(secret: str) -> dict[str, str]:
    value = secret.strip()
    if not value:
        raise CredentialError("api_key_missing", "API key cannot be empty")
    return {"secret": value}


def mask_identifier(value: str) -> str:
    clean = value.strip()
    if len(clean) <= 10:
        return "***"
    return f"{clean[:4]}…{clean[-4:]}"


def jwt_expiry(token: str | None) -> datetime | None:
    claims = decode_jwt_claims(token)
    exp = claims.get("exp") if claims else None
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        try:
            return datetime.fromtimestamp(float(exp), UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def extract_codex_account_id(token: str | None) -> str | None:
    claims = decode_jwt_claims(token)
    if not claims:
        return None
    nested = claims.get("https://api.openai.com/auth")
    if isinstance(nested, dict):
        account_id = _optional_string(nested.get("chatgpt_account_id"))
        if account_id:
            return account_id
    return _optional_string(claims.get("chatgpt_account_id"))


def extract_jwt_string(token: str | None, key: str) -> str | None:
    claims = decode_jwt_claims(token)
    return _optional_string(claims.get(key)) if claims else None


def decode_jwt_claims(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def parse_gemini_expiry(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return _parse_datetime(value)


def _decode_flow_token(value: str) -> dict[str, Any]:
    try:
        decrypted = SecretBox(get_settings().app_secret).decrypt(value)
        payload = json.loads(decrypted or "")
    except Exception as exc:
        raise CredentialError(
            "codex_device_flow_invalid",
            "The Codex device login state is invalid",
        ) from exc
    if not isinstance(payload, dict):
        raise CredentialError(
            "codex_device_flow_invalid",
            "The Codex device login state is invalid",
        )
    return payload


def _validate_document_size(document: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError) as exc:
        raise CredentialError(
            "credential_document_invalid",
            "Credential document must contain finite JSON values",
        ) from exc
    if len(encoded) > MAX_IMPORT_BYTES:
        raise CredentialError(
            "credential_document_too_large",
            f"Credential document cannot exceed {MAX_IMPORT_BYTES} UTF-8 bytes",
        )


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, number))


def _oauth_error_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    if not isinstance(body, dict):
        return "unknown"
    error = body.get("error")
    if isinstance(error, dict):
        error = error.get("code") or error.get("type")
    return str(error or body.get("status") or "unknown").strip().casefold()


def _mark_credential_error(
    credential: ProviderCredential,
    status: CredentialStatus,
    code: str,
) -> None:
    credential.status = status
    credential.last_error_code = code[:120]
    credential.last_validated_at = datetime.now(UTC)

import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.credentials import CredentialError, ResolvedCredential, resolve_credential
from app.models import (
    CredentialKind,
    ModelProfile,
    ModelProvider,
    ProviderCredential,
    UserModelAccess,
)

CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
CODEX_RELEASE_URL = "https://api.github.com/repos/openai/codex/releases/latest"
CODEX_PROFILE_BASE_URL = "https://chatgpt.com/backend-api/codex"
ANTHROPIC_PROFILE_BASE_URL = "https://api.anthropic.com"
DEFAULT_CODEX_CLIENT_VERSION = "0.145.0"
MODEL_DISCOVERY_TIMEOUT_SECONDS = 20
CODEX_VERSION_CACHE_SECONDS = 3_600

_version_lock = threading.Lock()
_cached_codex_version: tuple[str, float] | None = None


@dataclass(frozen=True)
class DiscoveredModel:
    model_id: str
    display_name: str
    description: str | None = None
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: tuple[str, ...] = ()


CLAUDE_CODE_SUBSCRIPTION_MODELS = (
    DiscoveredModel(
        model_id="opus",
        display_name="Claude Opus",
        description="Claude Code subscription alias resolved by Anthropic at runtime.",
        default_reasoning_effort="high",
        supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    ),
    DiscoveredModel(
        model_id="sonnet",
        display_name="Claude Sonnet",
        description="Claude Code subscription alias resolved by Anthropic at runtime.",
        default_reasoning_effort="high",
        supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    ),
    DiscoveredModel(
        model_id="haiku",
        display_name="Claude Haiku",
        description="Claude Code subscription alias resolved by Anthropic at runtime.",
        default_reasoning_effort="high",
        supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    ),
)


@dataclass(frozen=True)
class SyncedModel:
    profile: ModelProfile
    created: bool


@dataclass(frozen=True)
class ModelSyncResult:
    credential_id: uuid.UUID
    provider: ModelProvider
    discovered: int
    created: int
    existing: int
    models: tuple[SyncedModel, ...]


def sync_credential_models(
    session: Session,
    credential: ProviderCredential,
    owner_id: uuid.UUID,
    *,
    client: httpx.Client | None = None,
    client_version: str | None = None,
) -> ModelSyncResult:
    if credential.owner_id != owner_id or credential.archived_at is not None:
        raise CredentialError(
            "credential_unavailable",
            "The credential is unavailable",
        )
    if credential.kind == CredentialKind.codex_oauth:
        provider = ModelProvider.codex
        profile_base_url = CODEX_PROFILE_BASE_URL
        native_tools = True
        discovered = discover_codex_models(
            session,
            credential,
            client=client,
            client_version=client_version,
        )
    elif credential.kind == CredentialKind.anthropic_oauth:
        provider = ModelProvider.anthropic
        profile_base_url = ANTHROPIC_PROFILE_BASE_URL
        # The bridge returns validated ToolCall objects to the existing Runner
        # protocol even though Claude Code itself receives no direct tools.
        native_tools = True
        # The official Claude Code runtime exposes stable aliases rather than
        # a public per-account model catalog. Resolve the stored token locally
        # and let Anthropic enforce plan/model entitlement when a run starts.
        resolve_credential(
            session,
            credential,
            force_refresh=False,
            client=client,
        )
        discovered = list(CLAUDE_CODE_SUBSCRIPTION_MODELS)
    else:
        raise CredentialError(
            "model_discovery_unsupported",
            "Automatic model provisioning is available for Codex and Claude Code OAuth credentials",
        )

    profiles = session.scalars(
        select(ModelProfile).where(
            ModelProfile.credential_id == credential.id,
            ModelProfile.provider == provider,
            ModelProfile.archived_at.is_(None),
        )
    ).all()
    existing_by_model = {profile.model_id: profile for profile in profiles}
    accessible_profile_ids = set(
        session.scalars(select(UserModelAccess.model_profile_id).where(UserModelAccess.user_id == owner_id)).all()
    )
    used_names = {
        name.casefold()
        for name in session.scalars(
            select(ModelProfile.name)
            .join(
                UserModelAccess,
                UserModelAccess.model_profile_id == ModelProfile.id,
            )
            .where(
                UserModelAccess.user_id == owner_id,
                ModelProfile.archived_at.is_(None),
            )
        ).all()
    }

    synced: list[SyncedModel] = []
    created = 0
    for item in discovered:
        profile = existing_by_model.get(item.model_id)
        was_created = profile is None
        if profile is None:
            profile = ModelProfile(
                name=_unique_profile_name(
                    item.display_name,
                    credential.name,
                    used_names,
                ),
                provider=provider,
                base_url=profile_base_url,
                model_id=item.model_id,
                encrypted_api_key=None,
                credential_id=credential.id,
                native_tools=native_tools,
                parameters={},
                enabled=True,
            )
            session.add(profile)
            session.flush()
            existing_by_model[item.model_id] = profile
            created += 1
        if profile.id not in accessible_profile_ids:
            session.add(
                UserModelAccess(
                    user_id=owner_id,
                    model_profile_id=profile.id,
                )
            )
            accessible_profile_ids.add(profile.id)
        synced.append(SyncedModel(profile=profile, created=was_created))

    session.flush()
    return ModelSyncResult(
        credential_id=credential.id,
        provider=provider,
        discovered=len(discovered),
        created=created,
        existing=len(discovered) - created,
        models=tuple(synced),
    )


def discover_codex_models(
    session: Session,
    credential: ProviderCredential,
    *,
    client: httpx.Client | None = None,
    client_version: str | None = None,
) -> list[DiscoveredModel]:
    owns_client = client is None
    http = client or httpx.Client(timeout=MODEL_DISCOVERY_TIMEOUT_SECONDS)
    try:
        version = client_version or latest_codex_client_version()
        resolved = resolve_credential(
            session,
            credential,
            force_refresh=False,
            client=http,
        )
        response = _request_codex_models(http, resolved, version)
        if response.status_code in {401, 403}:
            resolved = resolve_credential(
                session,
                credential,
                force_refresh=True,
                client=http,
            )
            response = _request_codex_models(http, resolved, version)
    except httpx.TransportError as exc:
        raise CredentialError(
            "codex_models_unreachable",
            "The Codex model catalog could not be reached",
        ) from exc
    finally:
        if owns_client:
            http.close()

    if response.status_code in {401, 403}:
        raise CredentialError(
            "codex_models_rejected",
            "OpenAI rejected this Codex OAuth credential while listing models",
        )
    if not 200 <= response.status_code < 300:
        raise CredentialError(
            f"codex_models_http_{response.status_code}",
            f"The Codex model catalog returned HTTP {response.status_code}",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise CredentialError(
            "codex_models_response_invalid",
            "The Codex model catalog returned invalid JSON",
        ) from exc
    if not isinstance(body, dict) or not isinstance(body.get("models"), list):
        raise CredentialError(
            "codex_models_response_invalid",
            "The Codex model catalog response has no model list",
        )

    result: list[DiscoveredModel] = []
    seen: set[str] = set()
    for raw in body["models"]:
        if not isinstance(raw, dict) or raw.get("visibility") != "list":
            continue
        model_id = _clean_string(raw.get("slug"), maximum=200)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        display_name = _clean_string(raw.get("display_name"), maximum=120) or model_id
        efforts = tuple(
            effort
            for item in raw.get("supported_reasoning_levels", [])
            if isinstance(item, dict) and (effort := _clean_string(item.get("effort"), maximum=40))
        )
        result.append(
            DiscoveredModel(
                model_id=model_id,
                display_name=display_name,
                description=_clean_string(
                    raw.get("description"),
                    maximum=2_000,
                ),
                default_reasoning_effort=_clean_string(
                    raw.get("default_reasoning_level"),
                    maximum=40,
                ),
                supported_reasoning_efforts=efforts,
            )
        )
    if not result:
        raise CredentialError(
            "codex_models_empty",
            "The Codex account returned no selectable models",
        )
    return result


def latest_codex_client_version(
    *,
    client: httpx.Client | None = None,
) -> str:
    global _cached_codex_version

    now = time.monotonic()
    with _version_lock:
        if _cached_codex_version and now < _cached_codex_version[1]:
            return _cached_codex_version[0]

        owns_client = client is None
        http = client or httpx.Client(timeout=10)
        version = DEFAULT_CODEX_CLIENT_VERSION
        try:
            response = http.get(
                CODEX_RELEASE_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "the-evil-repository",
                },
            )
            if 200 <= response.status_code < 300:
                body = response.json()
                if isinstance(body, dict) and not body.get("draft") and not body.get("prerelease"):
                    candidate = _normalize_codex_version(body.get("name") or body.get("tag_name"))
                    if candidate:
                        version = candidate
        except (httpx.HTTPError, ValueError):
            pass
        finally:
            if owns_client:
                http.close()

        _cached_codex_version = (
            version,
            now + CODEX_VERSION_CACHE_SECONDS,
        )
        return version


def _request_codex_models(
    client: httpx.Client,
    credential: ResolvedCredential,
    client_version: str,
) -> httpx.Response:
    if credential.kind != CredentialKind.codex_oauth or not credential.account_id:
        raise CredentialError(
            "codex_account_missing",
            "The Codex OAuth credential has no ChatGPT account id",
        )
    return client.get(
        CODEX_MODELS_URL,
        params={"client_version": client_version},
        headers={
            "Authorization": f"Bearer {credential.token}",
            "ChatGPT-Account-Id": credential.account_id,
            "Accept": "application/json",
            "User-Agent": f"codex-cli/{client_version}",
        },
    )


def _unique_profile_name(
    display_name: str,
    credential_name: str,
    used_names: set[str],
) -> str:
    base = display_name[:120]
    if base.casefold() not in used_names:
        used_names.add(base.casefold())
        return base

    suffix = f" · {credential_name}"
    candidate = f"{display_name[: max(1, 120 - len(suffix))]}{suffix}"
    if candidate.casefold() not in used_names:
        used_names.add(candidate.casefold())
        return candidate

    index = 2
    while True:
        numbered_suffix = f"{suffix} {index}"
        candidate = f"{display_name[: max(1, 120 - len(numbered_suffix))]}{numbered_suffix}"
        if candidate.casefold() not in used_names:
            used_names.add(candidate.casefold())
            return candidate
        index += 1


def _normalize_codex_version(value: Any) -> str | None:
    clean = _clean_string(value, maximum=80)
    if not clean:
        return None
    match = re.search(r"(\d+\.\d+\.\d+)", clean)
    return match.group(1) if match else None


def _clean_string(value: Any, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean[:maximum] if clean else None

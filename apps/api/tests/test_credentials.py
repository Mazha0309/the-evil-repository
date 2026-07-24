import base64
import json
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth, credentials, model_profiles
from app.config import get_settings
from app.credentials import (
    CredentialError,
    decode_payload,
    encode_payload,
    normalize_codex_auth_document,
    normalize_gemini_auth_document,
    poll_codex_device_flow,
    resolve_credential,
    start_codex_device_flow,
)
from app.database import Base, get_session
from app.models import (
    CredentialKind,
    CredentialStatus,
    ProviderCredential,
    UserAccount,
    UserRole,
)


def jwt(claims: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def build_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(credentials.router, prefix="/api/v1")
    app.include_router(model_profiles.router, prefix="/api/v1")

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_codex_and_gemini_auth_documents_are_normalized() -> None:
    expiry = datetime.now(UTC) + timedelta(hours=1)
    account_id = "account-123456789"
    access_token = jwt(
        {
            "exp": expiry.timestamp(),
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account_id,
            },
        }
    )
    id_token = jwt({"email": "owner@example.com"})

    codex, hint, codex_expiry = normalize_codex_auth_document(
        {
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": access_token,
                "refresh_token": "codex-refresh",
                "id_token": id_token,
                "account_id": account_id,
            },
        }
    )
    gemini, gemini_hint, gemini_expiry = normalize_gemini_auth_document(
        {
            "access_token": "gemini-access",
            "refresh_token": "gemini-refresh",
            "expiry_date": int(expiry.timestamp() * 1000),
            "email": "gemini@example.com",
            "cloudaicompanionProject": "gemini-project",
        }
    )

    assert codex["account_id"] == account_id
    assert codex["refresh_token"] == "codex-refresh"
    assert hint == "owner@example.com"
    assert codex_expiry is not None
    assert abs((codex_expiry - expiry).total_seconds()) < 1
    assert gemini["project_id"] == "gemini-project"
    assert gemini_hint == "gemini@example.com"
    assert gemini_expiry is not None
    assert abs((gemini_expiry - expiry).total_seconds()) < 1


def test_codex_refresh_uses_json_and_persists_rotated_token() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
            },
        )

    with Session(engine) as session:
        owner = UserAccount(
            username="owner",
            password_hash="unused",
            role=UserRole.user,
        )
        session.add(owner)
        session.flush()
        credential = ProviderCredential(
            owner_id=owner.id,
            name="Codex",
            kind=CredentialKind.codex_oauth,
            encrypted_payload=encode_payload(
                {
                    "access_token": "old-access",
                    "refresh_token": "old-refresh",
                    "account_id": "account-123",
                }
            ),
            status=CredentialStatus.unchecked,
        )
        session.add(credential)
        session.flush()

        resolved = resolve_credential(
            session,
            credential,
            force_refresh=True,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        assert resolved.token == "new-access"
        assert resolved.account_id == "account-123"
        assert credential.status == CredentialStatus.ready
        assert credential.last_refreshed_at is not None
        assert decode_payload(credential)["refresh_token"] == "new-refresh"
        assert captured["url"] == "https://auth.openai.com/oauth/token"
        assert captured["content_type"] == "application/json"
        assert captured["body"] == {
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
            "grant_type": "refresh_token",
            "refresh_token": "old-refresh",
        }


def test_codex_refresh_surfaces_rotating_token_reuse() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "refresh_token_reused",
                    "message": "already used",
                }
            },
        )

    with Session(engine) as session:
        owner = UserAccount(
            username="owner",
            password_hash="unused",
            role=UserRole.user,
        )
        session.add(owner)
        session.flush()
        credential = ProviderCredential(
            owner_id=owner.id,
            name="Codex",
            kind=CredentialKind.codex_oauth,
            encrypted_payload=encode_payload(
                {
                    "access_token": "old-access",
                    "refresh_token": "old-refresh",
                    "account_id": "account-123",
                }
            ),
            status=CredentialStatus.unchecked,
        )
        session.add(credential)
        session.flush()

        with pytest.raises(CredentialError) as captured:
            resolve_credential(
                session,
                credential,
                force_refresh=True,
                client=httpx.Client(transport=httpx.MockTransport(handler)),
            )

        assert captured.value.code == "refresh_token_reused"
        assert "latest auth.json" in str(captured.value)
        assert credentials.credential_http_error(captured.value).status_code == 401
        assert credential.status == CredentialStatus.needs_reauth
        assert credential.last_error_code == "refresh_token_reused"


def test_gemini_refresh_rotates_token_and_handles_sqlite_naive_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    captured: dict = {}
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "gemini_oauth_client_id",
        "test-client-id",
    )
    monkeypatch.setattr(
        settings,
        "gemini_oauth_client_secret",
        "test-client-secret",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["form"] = dict(item.split("=", 1) for item in request.content.decode().split("&"))
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    with Session(engine) as session:
        owner = UserAccount(
            username="owner",
            password_hash="unused",
            role=UserRole.user,
        )
        session.add(owner)
        session.flush()
        credential = ProviderCredential(
            owner_id=owner.id,
            name="Gemini",
            kind=CredentialKind.gemini_oauth,
            encrypted_payload=encode_payload(
                {
                    "access_token": "old-access",
                    "refresh_token": "refresh-token",
                    "project_id": "project-123",
                }
            ),
            status=CredentialStatus.unchecked,
            # SQLite returns a naive datetime despite timezone=True.
            expires_at=(datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None),
        )
        session.add(credential)
        session.commit()

        resolved = resolve_credential(
            session,
            credential,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        session.commit()

        assert resolved.token == "new-access"
        assert resolved.project_id == "project-123"
        assert credential.status == CredentialStatus.ready
        assert credential.last_refreshed_at is not None
        assert decode_payload(credential)["refresh_token"] == "refresh-token"
        assert captured["url"] == "https://oauth2.googleapis.com/token"
        assert captured["form"]["grant_type"] == "refresh_token"
        assert captured["form"]["client_id"] == "test-client-id"
        assert captured["form"]["client_secret"] == "test-client-secret"


def test_gemini_refresh_requires_deployment_oauth_client_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_oauth_client_id", None)
    monkeypatch.setattr(settings, "gemini_oauth_client_secret", None)

    with Session(engine) as session:
        owner = UserAccount(
            username="owner",
            password_hash="unused",
            role=UserRole.user,
        )
        session.add(owner)
        session.flush()
        credential = ProviderCredential(
            owner_id=owner.id,
            name="Gemini",
            kind=CredentialKind.gemini_oauth,
            encrypted_payload=encode_payload(
                {
                    "refresh_token": "refresh-token",
                    "project_id": "project-123",
                }
            ),
            status=CredentialStatus.unchecked,
        )
        session.add(credential)
        session.flush()

        with pytest.raises(CredentialError) as captured:
            resolve_credential(session, credential)

    assert captured.value.code == "gemini_oauth_client_not_configured"


def test_codex_device_flow_is_bound_to_the_requesting_user() -> None:
    owner_id = uuid.uuid4()

    def start_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "device_auth_id": "device-id",
                "user_code": "ABCD-EFGH",
                "interval": 1,
                "expires_in": 600,
            },
        )

    state = start_codex_device_flow(
        owner_id,
        client=httpx.Client(transport=httpx.MockTransport(start_handler)),
    )

    with pytest.raises(
        CredentialError,
        match="belongs to another account",
    ) as caught:
        poll_codex_device_flow(uuid.uuid4(), state["flow_token"])

    assert caught.value.code == "codex_device_flow_owner_mismatch"


def test_credential_api_never_returns_secrets_and_enforces_compatibility() -> None:
    client = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "strong password"},
    )
    assert setup.status_code == 201
    csrf = setup.json()["csrf_token"]

    created_key = client.post(
        "/api/v1/credentials",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Primary API key",
            "kind": "api_key",
            "secret": "never-return-this",
        },
    )
    assert created_key.status_code == 201
    assert "secret" not in created_key.text
    assert "encrypted_payload" not in created_key.text

    account_id = "account-123456789"
    codex = client.post(
        "/api/v1/credentials/import",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Codex Pro",
            "kind": "codex_oauth",
            "document": {
                "tokens": {
                    "access_token": jwt(
                        {
                            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
                            "chatgpt_account_id": account_id,
                        }
                    ),
                    "refresh_token": "never-return-refresh",
                    "account_id": account_id,
                }
            },
        },
    )
    assert codex.status_code == 201
    assert "never-return-refresh" not in codex.text

    checked = client.post(
        f"/api/v1/credentials/{codex.json()['id']}/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert checked.status_code == 200
    assert checked.json()["status"] == "ready"
    assert checked.json()["last_refreshed_at"] is None

    wrong_protocol = client.post(
        "/api/v1/models",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Wrong protocol",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model_id": "claude-test",
            "credential_id": codex.json()["id"],
        },
    )
    assert wrong_protocol.status_code == 422
    assert wrong_protocol.json()["detail"]["code"] == "credential_kind_mismatch"

    missing_credential = client.post(
        "/api/v1/models",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Missing Codex login",
            "provider": "codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "model_id": "gpt-5.3-codex",
        },
    )
    assert missing_credential.status_code == 422
    assert missing_credential.json()["detail"]["code"] == "credential_required"

    wrong_codex_credential = client.post(
        "/api/v1/models",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Codex with API key",
            "provider": "codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "model_id": "gpt-5.3-codex",
            "credential_id": created_key.json()["id"],
        },
    )
    assert wrong_codex_credential.status_code == 422
    assert wrong_codex_credential.json()["detail"]["code"] == ("credential_kind_mismatch")

    model = client.post(
        "/api/v1/models",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Codex Pro model",
            "provider": "codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "model_id": "gpt-5.3-codex",
            "credential_id": codex.json()["id"],
            "parameters": {"reasoning": {"effort": "high"}},
        },
    )
    assert model.status_code == 201
    assert model.json()["credential_name"] == "Codex Pro"
    assert model.json()["credential_kind"] == "codex_oauth"

    blocked_delete = client.delete(
        f"/api/v1/credentials/{codex.json()['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert blocked_delete.status_code == 409


def test_anthropic_setup_token_is_encrypted_and_provisions_models() -> None:
    client = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "strong password"},
    )
    csrf = setup.json()["csrf_token"]
    secret = "claude-code-setup-token-never-return"

    created = client.post(
        "/api/v1/credentials",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Claude subscription",
            "kind": "anthropic_oauth",
            "secret": secret,
        },
    )

    assert created.status_code == 201
    assert created.json()["kind"] == "anthropic_oauth"
    assert created.json()["status"] == "ready"
    assert created.json()["account_hint"] == "Claude subscription"
    assert secret not in created.text
    assert "encrypted_payload" not in created.text

    synced = client.post(
        f"/api/v1/credentials/{created.json()['id']}/models/sync",
        headers={"X-CSRF-Token": csrf},
    )
    assert synced.status_code == 200
    assert synced.json()["provider"] == "anthropic"
    assert synced.json()["discovered"] == 3
    assert {
        item["model_id"] for item in synced.json()["models"]
    } == {"opus", "sonnet", "haiku"}

    models = client.get("/api/v1/models")
    assert models.status_code == 200
    assert all(
        model["credential_kind"] == "anthropic_oauth"
        for model in models.json()
    )

    replacement = "replacement-setup-token-never-return"
    replaced = client.patch(
        f"/api/v1/credentials/{created.json()['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"secret": replacement},
    )
    assert replaced.status_code == 200
    assert replaced.json()["status"] == "ready"
    assert replacement not in replaced.text

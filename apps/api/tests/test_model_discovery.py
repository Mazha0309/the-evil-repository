from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.credentials import encode_payload
from app.database import Base
from app.model_discovery import (
    CODEX_MODELS_URL,
    discover_codex_models,
    sync_credential_models,
)
from app.models import (
    CredentialKind,
    CredentialStatus,
    ModelProfile,
    ModelProvider,
    ProviderCredential,
    UserAccount,
    UserModelAccess,
    UserRole,
)


def make_owner() -> UserAccount:
    return UserAccount(
        username="oauth-owner",
        password_hash="unused",
        role=UserRole.user,
    )


def make_codex_credential(owner: UserAccount) -> ProviderCredential:
    return ProviderCredential(
        owner_id=owner.id,
        name="Codex OAuth",
        kind=CredentialKind.codex_oauth,
        encrypted_payload=encode_payload(
            {
                "access_token": "account-access-token",
                "refresh_token": "account-refresh-token",
                "account_id": "account-123",
            }
        ),
        status=CredentialStatus.ready,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def make_anthropic_credential(owner: UserAccount) -> ProviderCredential:
    return ProviderCredential(
        owner_id=owner.id,
        name="Claude Code OAuth",
        kind=CredentialKind.anthropic_oauth,
        encrypted_payload=encode_payload(
            {"oauth_token": "claude-setup-token"}
        ),
        status=CredentialStatus.ready,
    )


def catalog_response(request: httpx.Request) -> httpx.Response:
    assert str(request.url).startswith(CODEX_MODELS_URL)
    assert request.url.params["client_version"] == "0.145.0"
    assert request.headers["authorization"] == "Bearer account-access-token"
    assert request.headers["chatgpt-account-id"] == "account-123"
    return httpx.Response(
        200,
        json={
            "models": [
                {
                    "slug": "gpt-visible",
                    "display_name": "GPT Visible",
                    "description": "Selectable",
                    "visibility": "list",
                    "default_reasoning_level": "medium",
                    "supported_reasoning_levels": [
                        {"effort": "low"},
                        {"effort": "medium"},
                    ],
                },
                {
                    "slug": "gpt-second",
                    "display_name": "GPT Second",
                    "visibility": "list",
                    "supported_in_api": False,
                },
                {
                    "slug": "internal-review",
                    "display_name": "Internal Review",
                    "visibility": "hide",
                },
                {
                    "slug": "gpt-visible",
                    "display_name": "Duplicate",
                    "visibility": "list",
                },
            ]
        },
    )


def test_codex_discovery_uses_account_catalog_and_filters_hidden_models() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        owner = make_owner()
        session.add(owner)
        session.flush()
        credential = make_codex_credential(owner)
        session.add(credential)
        session.flush()

        models = discover_codex_models(
            session,
            credential,
            client=httpx.Client(transport=httpx.MockTransport(catalog_response)),
            client_version="0.145.0",
        )

        assert [model.model_id for model in models] == [
            "gpt-visible",
            "gpt-second",
        ]
        assert models[0].display_name == "GPT Visible"
        assert models[0].default_reasoning_effort == "medium"
        assert models[0].supported_reasoning_efforts == ("low", "medium")


def test_codex_model_sync_creates_accessible_profiles_and_is_idempotent() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        owner = make_owner()
        session.add(owner)
        session.flush()
        credential = make_codex_credential(owner)
        conflicting_name = ModelProfile(
            name="GPT Visible",
            provider=ModelProvider.openai_responses,
            base_url="https://api.openai.com/v1",
            model_id="gpt-visible",
            encrypted_api_key="legacy",
            native_tools=True,
            parameters={},
            enabled=True,
        )
        session.add_all([credential, conflicting_name])
        session.flush()
        session.add(
            UserModelAccess(
                user_id=owner.id,
                model_profile_id=conflicting_name.id,
            )
        )
        session.flush()
        client = httpx.Client(transport=httpx.MockTransport(catalog_response))

        first = sync_credential_models(
            session,
            credential,
            owner.id,
            client=client,
            client_version="0.145.0",
        )
        second = sync_credential_models(
            session,
            credential,
            owner.id,
            client=client,
            client_version="0.145.0",
        )

        assert first.discovered == 2
        assert first.created == 2
        assert first.existing == 0
        assert second.created == 0
        assert second.existing == 2
        profiles = session.scalars(
            select(ModelProfile).where(ModelProfile.credential_id == credential.id).order_by(ModelProfile.model_id)
        ).all()
        assert [profile.model_id for profile in profiles] == [
            "gpt-second",
            "gpt-visible",
        ]
        assert all(profile.provider == ModelProvider.codex for profile in profiles)
        assert all(profile.base_url == "https://chatgpt.com/backend-api/codex" for profile in profiles)
        assert (
            next(profile for profile in profiles if profile.model_id == "gpt-visible").name
            == "GPT Visible · Codex OAuth"
        )
        access_ids = set(
            session.scalars(select(UserModelAccess.model_profile_id).where(UserModelAccess.user_id == owner.id)).all()
        )
        assert {profile.id for profile in profiles}.issubset(access_ids)


def test_anthropic_oauth_sync_provisions_official_runtime_aliases() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        owner = make_owner()
        session.add(owner)
        session.flush()
        credential = make_anthropic_credential(owner)
        session.add(credential)
        session.flush()

        first = sync_credential_models(session, credential, owner.id)
        second = sync_credential_models(session, credential, owner.id)

        assert first.provider == ModelProvider.anthropic
        assert first.discovered == 3
        assert first.created == 3
        assert second.created == 0
        assert second.existing == 3
        profiles = session.scalars(
            select(ModelProfile)
            .where(ModelProfile.credential_id == credential.id)
            .order_by(ModelProfile.model_id)
        ).all()
        assert [profile.model_id for profile in profiles] == [
            "haiku",
            "opus",
            "sonnet",
        ]
        assert all(
            profile.provider == ModelProvider.anthropic
            for profile in profiles
        )
        assert all(
            profile.base_url == "https://api.anthropic.com"
            for profile in profiles
        )
        assert all(profile.native_tools for profile in profiles)

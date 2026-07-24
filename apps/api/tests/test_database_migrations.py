from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.database as database
from app.credentials import decode_payload
from app.crypto import SecretBox
from app.models import (
    ModelProfile,
    ModelProvider,
    ProviderCredential,
    UserAccount,
    UserModelAccess,
    UserRole,
)


def test_create_schema_adds_archive_columns_to_legacy_sqlite(
    monkeypatch,
) -> None:
    legacy_engine = create_engine("sqlite://")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE platform_settings "
                "(name VARCHAR(80) PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE model_profiles "
                "(id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO model_profiles (id) VALUES ('legacy-profile')")
        )
        connection.execute(
            text(
                "CREATE TABLE benchmark_runs "
                "(id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO benchmark_runs (id) VALUES ('legacy-run')")
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.create_schema()
    database.create_schema()

    with legacy_engine.connect() as connection:
        model_columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(model_profiles)")
            )
        }
        run_columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(benchmark_runs)")
            )
        }
        stored_model = connection.execute(
            text(
                "SELECT id, archived_at FROM model_profiles "
                "WHERE id = 'legacy-profile'"
            )
        ).one()
        stored_run = connection.execute(
            text(
                "SELECT id, archived_at FROM benchmark_runs "
                "WHERE id = 'legacy-run'"
            )
        ).one()

    assert {"archived_at", "credential_id"} <= model_columns
    assert "archived_at" in run_columns
    assert stored_model == ("legacy-profile", None)
    assert stored_run == ("legacy-run", None)


def test_legacy_profile_key_migrates_to_one_reusable_credential(
    monkeypatch,
) -> None:
    legacy_engine = create_engine("sqlite://")
    database.Base.metadata.create_all(legacy_engine)
    sessions = sessionmaker(
        bind=legacy_engine,
        expire_on_commit=False,
        class_=Session,
    )
    monkeypatch.setattr(database, "engine", legacy_engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)

    with sessions() as session:
        owner = UserAccount(
            username="legacy-owner",
            password_hash="unused",
            role=UserRole.user,
        )
        profile = ModelProfile(
            name="Legacy model",
            provider=ModelProvider.openai_compatible,
            base_url="https://provider.example/v1",
            model_id="legacy-model",
            encrypted_api_key=SecretBox(
                database.settings.app_secret
            ).encrypt("legacy-secret"),
        )
        session.add_all([owner, profile])
        session.flush()
        session.add(
            UserModelAccess(
                user_id=owner.id,
                model_profile_id=profile.id,
            )
        )
        session.commit()
        profile_id = profile.id

    database.migrate_legacy_model_credentials()
    database.migrate_legacy_model_credentials()

    with sessions() as session:
        migrated = session.get(ModelProfile, profile_id)
        credentials = list(
            session.scalars(select(ProviderCredential)).all()
        )
        assert migrated is not None
        assert migrated.encrypted_api_key is None
        assert migrated.credential_id == credentials[0].id
        assert len(credentials) == 1
        assert credentials[0].name == "Legacy model · API key"
        assert decode_payload(credentials[0]) == {"secret": "legacy-secret"}

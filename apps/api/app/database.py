from collections.abc import Generator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def create_schema() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            for value in ("openai_responses", "anthropic", "codex", "gemini"):
                connection.execute(text(f"ALTER TYPE modelprovider ADD VALUE IF NOT EXISTS '{value}'"))
            connection.execute(text("ALTER TABLE model_profiles DROP CONSTRAINT IF EXISTS model_profiles_name_key"))
            connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'user_accounts' AND column_name = 'email'
                        ) AND NOT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'user_accounts' AND column_name = 'username'
                        ) THEN
                            ALTER TABLE user_accounts RENAME COLUMN email TO username;
                        END IF;
                    END
                    $$;
                    """
                )
            )
            connection.execute(text("ALTER TABLE user_accounts DROP COLUMN IF EXISTS display_name"))
            connection.execute(text("ALTER TABLE user_accounts ALTER COLUMN username TYPE VARCHAR(32)"))
            connection.execute(
                text(
                    "ALTER TABLE platform_settings "
                    "ADD COLUMN IF NOT EXISTS runner_concurrency INTEGER "
                    f"NOT NULL DEFAULT {settings.runner_concurrency}"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE model_profiles "
                    "ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITH TIME ZONE"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE model_profiles "
                    "ADD COLUMN IF NOT EXISTS credential_id UUID "
                    "REFERENCES provider_credentials(id) ON DELETE SET NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_model_profiles_credential_id "
                    "ON model_profiles (credential_id)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE benchmark_runs "
                    "ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITH TIME ZONE"
                )
            )
        finally:
            connection.close()
    elif engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            platform_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(platform_settings)"))
            }
            if "runner_concurrency" not in platform_columns:
                connection.execute(
                    text(
                        "ALTER TABLE platform_settings "
                        "ADD COLUMN runner_concurrency INTEGER "
                        f"NOT NULL DEFAULT {settings.runner_concurrency}"
                    )
                )
            model_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(model_profiles)"))
            }
            if "archived_at" not in model_columns:
                connection.execute(
                    text("ALTER TABLE model_profiles ADD COLUMN archived_at DATETIME")
                )
            if "credential_id" not in model_columns:
                connection.execute(
                    text(
                        "ALTER TABLE model_profiles "
                        "ADD COLUMN credential_id CHAR(32) "
                        "REFERENCES provider_credentials(id) ON DELETE SET NULL"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_model_profiles_credential_id "
                        "ON model_profiles (credential_id)"
                    )
                )
            run_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(benchmark_runs)"))
            }
            if "archived_at" not in run_columns:
                connection.execute(
                    text("ALTER TABLE benchmark_runs ADD COLUMN archived_at DATETIME")
                )
    migrate_legacy_model_credentials()


def migrate_legacy_model_credentials() -> None:
    from app.credentials import create_api_key_payload, encode_payload
    from app.crypto import SecretBox
    from app.models import (
        CredentialKind,
        CredentialStatus,
        ModelProfile,
        ProviderCredential,
        UserModelAccess,
    )

    model_columns = {
        column["name"] for column in inspect(engine).get_columns("model_profiles")
    }
    if not {"credential_id", "encrypted_api_key", "archived_at"}.issubset(
        model_columns
    ):
        return

    box = SecretBox(settings.app_secret)
    with SessionLocal() as session:
        profiles = session.scalars(
            select(ModelProfile).where(
                ModelProfile.credential_id.is_(None),
                ModelProfile.encrypted_api_key.is_not(None),
                ModelProfile.archived_at.is_(None),
            )
        ).all()
        changed = False
        for profile in profiles:
            access = session.scalar(
                select(UserModelAccess)
                .where(UserModelAccess.model_profile_id == profile.id)
                .order_by(UserModelAccess.created_at, UserModelAccess.user_id)
            )
            if access is None:
                continue
            secret = box.decrypt(profile.encrypted_api_key)
            if not secret:
                continue
            base_name = f"{profile.name} · API key"
            name = base_name
            suffix = 2
            while session.scalar(
                select(ProviderCredential.id).where(
                    ProviderCredential.owner_id == access.user_id,
                    ProviderCredential.name == name,
                    ProviderCredential.archived_at.is_(None),
                )
            ):
                name = f"{base_name} {suffix}"
                suffix += 1
            credential = ProviderCredential(
                owner_id=access.user_id,
                name=name,
                kind=CredentialKind.api_key,
                encrypted_payload=encode_payload(create_api_key_payload(secret)),
                status=CredentialStatus.ready,
            )
            session.add(credential)
            session.flush()
            profile.credential_id = credential.id
            profile.encrypted_api_key = None
            changed = True
        if changed:
            session.commit()

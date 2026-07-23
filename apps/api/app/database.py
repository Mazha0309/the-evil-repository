from collections.abc import Generator

from sqlalchemy import create_engine, text
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
            for value in ("openai_responses", "anthropic"):
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
        finally:
            connection.close()

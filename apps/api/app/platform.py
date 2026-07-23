from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PlatformSettings


def ensure_platform_settings(session: Session) -> PlatformSettings:
    settings = session.get(PlatformSettings, "default")
    if settings is None:
        settings = PlatformSettings(
            name="default",
            registration_enabled=False,
            runner_concurrency=get_settings().runner_concurrency,
        )
        session.add(settings)
        session.flush()
    return settings

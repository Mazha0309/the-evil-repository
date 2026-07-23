from sqlalchemy.orm import Session

from app.models import PlatformSettings


def ensure_platform_settings(session: Session) -> PlatformSettings:
    settings = session.get(PlatformSettings, "default")
    if settings is None:
        settings = PlatformSettings(name="default", registration_enabled=False)
        session.add(settings)
        session.flush()
    return settings

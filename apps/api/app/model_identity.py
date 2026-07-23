from app.models import ModelProfile


def model_snapshot(profile: ModelProfile) -> dict[str, str]:
    """Freeze non-secret model identity for durable run attribution."""

    return {
        "profile_id": str(profile.id),
        "name": profile.name,
        "provider": profile.provider.value,
        "model_id": profile.model_id,
    }

from typing import Any

from app.models import ModelProfile, TaskDefinition


def model_snapshot(profile: ModelProfile) -> dict[str, str]:
    """Freeze non-secret model identity for durable run attribution."""

    return {
        "profile_id": str(profile.id),
        "name": profile.name,
        "provider": profile.provider.value,
        "model_id": profile.model_id,
    }


def task_snapshot(task: TaskDefinition) -> dict[str, Any]:
    """Freeze non-secret Scenario identity for durable run attribution."""

    return {
        "id": str(task.id),
        "slug": task.slug,
        "version": task.version,
        "name": task.name,
        "description": task.description,
        "localizations": task.manifest.get("localizations", {}),
    }

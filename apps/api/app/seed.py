import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TaskDefinition
from app.scenario.sdk import ScenarioMetadata


def seed_canonical_task(session: Session) -> None:
    scenarios_root = get_settings().scenarios_root
    if not scenarios_root.exists():
        return
    for metadata_path in sorted(scenarios_root.glob("*/metadata.yaml")):
        manifest = ScenarioMetadata.model_validate(yaml.safe_load(metadata_path.read_text(encoding="utf-8")))
        older_versions = session.scalars(
            select(TaskDefinition).where(
                TaskDefinition.slug == manifest.slug,
                TaskDefinition.version != manifest.version,
            )
        ).all()
        for older in older_versions:
            older.enabled = False
        existing = session.scalar(
            select(TaskDefinition).where(
                TaskDefinition.slug == manifest.slug,
                TaskDefinition.version == manifest.version,
            )
        )
        if existing:
            existing.name = manifest.name
            existing.description = manifest.description
            existing.category = "terminal"
            existing.kind = "scenario"
            existing.manifest = manifest.model_dump(mode="json")
            existing.enabled = True
            continue
        session.add(
            TaskDefinition(
                slug=manifest.slug,
                version=manifest.version,
                name=manifest.name,
                description=manifest.description,
                category="terminal",
                kind="scenario",
                manifest=manifest.model_dump(mode="json"),
            )
        )
    session.commit()

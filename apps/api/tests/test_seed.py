from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import TaskDefinition
from app.seed import seed_canonical_task


def test_canonical_seed_enables_v3_patch_and_retires_v1(monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[3]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.seed.get_settings",
        lambda: SimpleNamespace(scenarios_root=project_root / "scenarios"),
    )

    with Session(engine) as session:
        session.add(
            TaskDefinition(
                slug="terminal-repository",
                version="1.0.0",
                name="The Terminal Repository",
                description="old",
                category="terminal",
                kind="scenario",
                manifest={},
                enabled=True,
            )
        )
        session.commit()

        seed_canonical_task(session)
        seed_canonical_task(session)

        tasks = list(
            session.scalars(
                select(TaskDefinition)
                .where(TaskDefinition.slug == "terminal-repository")
                .order_by(TaskDefinition.version)
            ).all()
        )

    assert [(task.version, task.enabled) for task in tasks] == [
        ("1.0.0", False),
        ("3.0.1", True),
    ]
    assert tasks[1].manifest["completion"]["min_tool_calls"] == 0
    assert tasks[1].manifest["incident"]["enabled"] is True
    assert len(tasks[1].manifest["incident"]["required_decisions"]) == 8

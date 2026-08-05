import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.dashboard import dashboard_summary
from app.api.runs import archive_run, get_run, list_runs
from app.database import Base
from app.models import (
    BenchmarkRun,
    ModelProfile,
    ModelProvider,
    RunEvent,
    RunStatus,
    TaskDefinition,
    UserAccount,
    UserModelAccess,
    UserRole,
    UserRunAccess,
)


def seed_run(
    session: Session,
    *,
    status: RunStatus,
) -> tuple[UserAccount, BenchmarkRun]:
    user = UserAccount(
        username=f"owner-{status.value}",
        password_hash="not-used",
        role=UserRole.user,
        enabled=True,
    )
    model = ModelProfile(
        name=f"model-{status.value}",
        provider=ModelProvider.openai_compatible,
        base_url="https://provider.example/v1",
        model_id="candidate",
        enabled=True,
    )
    task = TaskDefinition(
        slug=f"archive-{status.value}",
        version="1.0.0",
        name="Archive test",
        description="Test run archival",
        category="test",
        manifest={},
        enabled=True,
    )
    session.add_all([user, model, task])
    session.flush()
    run = BenchmarkRun(
        task_id=task.id,
        candidate_model_id=model.id,
        status=status,
        stage=status.value,
        score=777 if status == RunStatus.completed else None,
        scorecard={"dimensions": {}},
        config={},
    )
    session.add(run)
    session.flush()
    session.add_all(
        [
            UserModelAccess(
                user_id=user.id,
                model_profile_id=model.id,
            ),
            UserRunAccess(
                user_id=user.id,
                run_id=run.id,
            ),
            RunEvent(
                run_id=run.id,
                sequence=1,
                kind="run.completed",
                payload={},
            ),
        ]
    )
    session.commit()
    return user, run

def test_archive_run_hides_terminal_result_without_deleting_evidence() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user, run = seed_run(session, status=RunStatus.completed)
        run_id = run.id

        archive_run(run_id, session, user)
        session.expire_all()

        stored = session.get(BenchmarkRun, run_id)
        assert stored is not None
        assert stored.archived_at is not None
        assert stored.status == RunStatus.completed
        assert stored.score == 777
        assert list_runs(session, user) == []
        summary = dashboard_summary(session, user)
        assert summary.total_runs == 0
        assert summary.completed_runs == 0
        assert summary.average_score is None
        assert session.get(
            UserRunAccess,
            {"user_id": user.id, "run_id": run_id},
        ) is not None
        events = list(
            session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .order_by(RunEvent.sequence)
            ).all()
        )
        assert [event.kind for event in events] == [
            "run.completed",
            "run.archived",
        ]

        with pytest.raises(HTTPException) as error:
            get_run(run_id, session, user)
        assert error.value.status_code == 404

def test_archive_run_rejects_active_result() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user, run = seed_run(session, status=RunStatus.running)

        with pytest.raises(HTTPException) as error:
            archive_run(run.id, session, user)

        assert error.value.status_code == 409
        assert "finish or be cancelled" in error.value.detail
        session.refresh(run)
        assert run.archived_at is None

def test_dashboard_average_excludes_censored_completed_run() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user, run = seed_run(session, status=RunStatus.completed)
        run.scorecard = {
            "resources": {"hard_limits_crossed": ["active_time"]},
        }
        session.commit()

        summary = dashboard_summary(session, user)

        assert summary.completed_runs == 1
        assert summary.average_score is None

def test_archive_schema_v3_includes_new_telemetry_files(tmp_path: Path) -> None:
    import json
    import tarfile

    from app.scenario import PreparedScenario, ScenarioRunResult, load_scenario

    scenario_root = (
        Path(__file__).resolve().parents[3] / "scenarios" / "terminal-repository"
    )
    scenario = load_scenario(scenario_root)
    prepared = PreparedScenario(
        scenario_root=scenario_root,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    result = ScenarioRunResult(
        final_response="done",
        elapsed_seconds=12,
        tool_calls=1,
        events=[
            {"sequence": 1, "kind": "run.turn.begin", "turn": 1, "tool_calls": 0},
            {
                "sequence": 2,
                "kind": "run.budget_adjusted",
                "field": "hard_tool_calls",
                "new_value": 5000,
            },
            {
                "sequence": 3,
                "kind": "run.turn.end",
                "turn": 1,
                "tool_calls": 2,
                "duration_ms": 100,
            },
        ],
        artifacts={
            "scorecard.json": '{"score": 777, "dimensions": {}}',
            "dead-letter.diff": (
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -1,1 +1,2 @@\n"
                "- old\n"
                "+ new\n"
            ),
        },
        private_state={
            "resource_ledger": {"hard_tool_calls": 5000, "active_time_ms": 12_000},
            "investigation_graph": {
                "hypotheses": [],
                "revisions": [],
                "evidence": [],
                "edges": [],
            },
        },
    )

    destination = scenario.archive(prepared, result, tmp_path / "run.tar.gz")

    with tarfile.open(destination, "r:gz") as archive:
        names = set(archive.getnames())
        assert {
            "telemetry/budget-adjustments.jsonl",
            "telemetry/turn-boundaries.jsonl",
            "resource-ledger.json",
            "export.json",
        } <= names
        manifest = json.loads(archive.extractfile("run.json").read())
        export = json.loads(archive.extractfile("export.json").read())
        budget_lines = archive.extractfile(
            "telemetry/budget-adjustments.jsonl"
        ).read().decode().splitlines()
        turn_lines = archive.extractfile(
            "telemetry/turn-boundaries.jsonl"
        ).read().decode().splitlines()
        resource_ledger = json.loads(
            archive.extractfile("resource-ledger.json").read()
        )

    assert manifest["archive_schema_version"] == 3
    assert budget_lines == [
        json.dumps(
            {
                "sequence": 2,
                "kind": "run.budget_adjusted",
                "field": "hard_tool_calls",
                "new_value": 5000,
            },
            sort_keys=True,
        )
    ]
    assert len(turn_lines) == 2
    assert resource_ledger["hard_tool_calls"] == 5000
    assert export["export_schema_version"] == 3
    assert export["budget_adjustment_count"] == 1
    assert export["budget_adjustment_fields"] == ["hard_tool_calls"]
    assert export["diffs"] == [
        {
            "repo": "dead-letter",
            "added_lines": 1,
            "removed_lines": 1,
            "file_count": 1,
            "sha256": hashlib.sha256(
                b"diff --git a/README.md b/README.md\n"
                b"--- a/README.md\n"
                b"+++ b/README.md\n"
                b"@@ -1,1 +1,2 @@\n"
                b"- old\n"
                b"+ new\n"
            ).hexdigest(),
        }
    ]
    assert export["turn_summary"] == {
        "total_turns": 1,
        "completed_turns": 1,
        "average_duration_ms": 100.0,
        "max_duration_ms": 100.0,
    }
    assert export["result"] == {
        "elapsed_seconds": 12,
        "tool_calls": 1,
        "final_response_length": 4,
    }
    assert export["scorecard"]["score"] == 777

def test_archive_v3_turn_summary_handles_unpaired_begins_and_missing_duration(
    tmp_path: Path,
) -> None:
    import json
    import tarfile

    from app.scenario import PreparedScenario, ScenarioRunResult, load_scenario

    scenario_root = (
        Path(__file__).resolve().parents[3] / "scenarios" / "terminal-repository"
    )
    scenario = load_scenario(scenario_root)
    prepared = PreparedScenario(
        scenario_root=scenario_root,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    result = ScenarioRunResult(
        final_response="done",
        elapsed_seconds=12,
        tool_calls=1,
        events=[
            {"sequence": 1, "kind": "run.turn.begin", "turn": 1, "tool_calls": 0},
            {"sequence": 2, "kind": "run.turn.begin", "turn": 2, "tool_calls": 0},
            {"sequence": 3, "kind": "run.turn.begin", "turn": 3, "tool_calls": 0},
            {
                "sequence": 4,
                "kind": "run.turn.end",
                "turn": 1,
                "tool_calls": 2,
                "duration_ms": 100,
            },
            {
                "sequence": 5,
                "kind": "run.turn.end",
                "turn": 1,
                "tool_calls": 2,
                "duration_ms": 999,
            },
            {"sequence": 6, "kind": "run.turn.end", "turn": 2, "tool_calls": 1},
            {
                "sequence": 7,
                "kind": "run.turn.end",
                "turn": 4,
                "tool_calls": 1,
                "duration_ms": 50,
            },
        ],
        artifacts={},
    )

    destination = scenario.archive(prepared, result, tmp_path / "run.tar.gz")

    with tarfile.open(destination, "r:gz") as archive:
        export = json.loads(archive.extractfile("export.json").read())

    assert export["turn_summary"] == {
        "total_turns": 3,
        "completed_turns": 2,
        "average_duration_ms": 100.0,
        "max_duration_ms": 100.0,
    }
    assert export["budget_adjustment_count"] == 0


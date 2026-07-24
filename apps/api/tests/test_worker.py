import json
import tarfile
import uuid
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.worker as worker_module
from app.database import Base
from app.judging import SemanticJudgeOutcome
from app.models import (
    BenchmarkRun,
    ModelProvider,
    RunArtifact,
    RunEvent,
    RunStatus,
)
from app.runner.protocol import ToolResult
from app.scenario import PreparedScenario, load_scenario
from app.scenario.sdk import ScenarioRunResult
from app.worker import Worker

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_ROOT = PROJECT_ROOT / "scenarios" / "terminal-repository"


class FakeSession:
    def __init__(self, run: SimpleNamespace) -> None:
        self.run = run
        self.commits = 0

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, _model: object, _identifier: object) -> SimpleNamespace:
        return self.run

    def scalar(self, _statement: object) -> SimpleNamespace:
        return self.run

    def commit(self) -> None:
        self.commits += 1


def test_hidden_check_publishes_started_and_completed_events(monkeypatch) -> None:
    run = SimpleNamespace(status=RunStatus.running, stage="Candidate investigation")
    session = FakeSession(run)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_module,
        "append_event",
        lambda _session, _run_id, kind, payload: events.append((kind, payload)),
    )
    expected = ToolResult(
        call_id="hidden-static",
        name="static",
        status="ok",
        output="passed",
    )

    result = Worker().hidden_check(
        uuid.uuid4(),
        "static",
        lambda: expected,
    )

    assert result is expected
    assert run.stage == "Hidden judge · static"
    assert [kind for kind, _ in events] == [
        "judge.check.started",
        "judge.check.completed",
    ]
    assert events[-1][1]["check"] == "static"
    assert events[-1][1]["status"] == "ok"
    assert int(events[-1][1]["duration_ms"]) >= 0


def test_runner_startup_marks_interrupted_runs_as_non_resumable(
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )
    interrupted_id = uuid.uuid4()
    queued_id = uuid.uuid4()
    with testing_session() as session:
        session.add_all(
            [
                BenchmarkRun(
                    id=interrupted_id,
                    task_id=uuid.uuid4(),
                    candidate_model_id=uuid.uuid4(),
                    status=RunStatus.running,
                    stage="Pause requested",
                    config={"pause_requested": True},
                ),
                BenchmarkRun(
                    id=queued_id,
                    task_id=uuid.uuid4(),
                    candidate_model_id=uuid.uuid4(),
                    status=RunStatus.queued,
                    stage="Queued",
                    config={},
                ),
            ]
        )
        session.commit()
    monkeypatch.setattr(worker_module, "SessionLocal", testing_session)

    reconciled = Worker.reconcile_orphaned_runs()

    assert reconciled == 1
    with testing_session() as session:
        interrupted = session.get(BenchmarkRun, interrupted_id)
        queued = session.get(BenchmarkRun, queued_id)
        event = session.scalar(select(RunEvent).where(RunEvent.run_id == interrupted_id))
        assert interrupted is not None
        assert interrupted.status == RunStatus.failed
        assert interrupted.stage == "Interrupted by Runner restart"
        assert interrupted.config["pause_requested"] is False
        assert interrupted.completed_at is not None
        assert "cannot be resumed safely" in str(interrupted.error)
        assert event is not None
        assert event.kind == "run.orphaned"
        assert event.payload == {
            "reason": "runner_restart",
            "resumable": False,
            "previous_status": "running",
            "previous_stage": "Pause requested",
        }
        assert queued is not None
        assert queued.status == RunStatus.queued


def test_worker_fills_configured_parallel_run_slots(monkeypatch) -> None:
    worker = Worker()
    run_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    claimed = iter(run_ids)
    submitted: list[uuid.UUID] = []

    class FakeExecutor:
        def submit(self, _callback, run_id: uuid.UUID) -> Future[None]:
            submitted.append(run_id)
            return Future()

    monkeypatch.setattr(worker, "concurrency_limit", lambda: 2)
    monkeypatch.setattr(worker, "claim", lambda: next(claimed, None))
    futures: dict[Future[None], uuid.UUID] = {}

    count = worker.fill_available_slots(FakeExecutor(), futures)

    assert count == 2
    assert submitted == run_ids[:2]
    assert list(futures.values()) == run_ids[:2]


def test_worker_tracks_active_run_while_thread_executes(monkeypatch) -> None:
    worker = Worker()
    run_id = uuid.uuid4()
    observed: list[int] = []
    monkeypatch.setattr(
        worker,
        "execute",
        lambda _run_id: observed.append(worker.active_run_count()),
    )

    worker.execute_tracked(run_id)

    assert observed == [1]
    assert worker.active_run_count() == 0


def test_cancelled_run_cannot_be_resurrected_by_completion(monkeypatch) -> None:
    run = SimpleNamespace(status=RunStatus.cancelled, stage="Cancelled by user")
    session = FakeSession(run)
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: session)

    Worker().complete(
        uuid.uuid4(),
        ScenarioRunResult("", 0, 0, []),
        {"score": 1_200, "maximum": 1_200},
        Path("/archive-must-not-be-read.tar.gz"),
        "unused",
    )

    assert run.status == RunStatus.cancelled
    assert run.stage == "Cancelled by user"
    assert session.commits == 0


def test_budget_exhausted_run_is_archived_as_censored_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )
    run_id = uuid.uuid4()
    with testing_session() as session:
        session.add(
            BenchmarkRun(
                id=run_id,
                task_id=uuid.uuid4(),
                candidate_model_id=uuid.uuid4(),
                status=RunStatus.scoring,
                stage="Scorecard aggregation",
                config={},
            )
        )
        session.commit()
    archive = tmp_path / "run.tar.gz"
    archive.write_bytes(b"archive")
    monkeypatch.setattr(worker_module, "SessionLocal", testing_session)
    result = ScenarioRunResult(
        final_response="Hard scenario budget reached.",
        elapsed_seconds=10_800,
        tool_calls=900,
        events=[],
        private_state={
            "input_tokens": 100,
            "output_tokens": 20,
            "hard_budget_reasons": ["active_time"],
        },
    )
    scorecard = {
        "score": 85,
        "maximum": 1_200,
        "outcome": {
            "status": "budget_exhausted",
            "censored": True,
            "hard_budget_reasons": ["active_time"],
        },
    }

    Worker().complete(
        run_id,
        result,
        scorecard,
        archive,
        "c" * 64,
    )

    with testing_session() as session:
        run = session.get(BenchmarkRun, run_id)
        events = list(
            session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .order_by(RunEvent.sequence)
            ).all()
        )
        assert run is not None
        assert run.status == RunStatus.completed
        assert run.stage == "Budget exhausted"
        assert run.score == 85
        assert [event.kind for event in events] == [
            "run.budget_exhausted",
            "run.completed",
        ]
        assert events[0].payload["censored"] is True
        assert events[1].payload["outcome"] == "budget_exhausted"


def test_failure_checkpoint_preserves_events_diffs_and_resource_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path / "workspace",
        metadata=scenario.metadata,
        private_state={
            "truth": {
                "dead_letter_baseline": "dead-base",
                "palimpsest_baseline": "pal-base",
            }
        },
    )
    result = ScenarioRunResult(
        final_response="interrupted",
        elapsed_seconds=123,
        tool_calls=17,
        events=[],
        private_state={
            "resource_ledger": {
                "provider_requests": 7,
                "tool_calls": 17,
            },
            "incident_audit": {"risk": 2},
        },
    )
    engine = SimpleNamespace(
        checkpoint_result=lambda _error: result,
    )
    sandbox = SimpleNamespace(
        container=object(),
        git_diff=lambda repository, baseline: f"{repository}:{baseline}:diff",
        git_status=lambda repository: f"{repository}:dirty",
        collect_text=lambda path: (
            "# Investigation checkpoint" if path == "INVESTIGATION.md" else ""
        ),
    )
    worker = Worker()
    run_id = uuid.uuid4()
    monkeypatch.setattr(worker_module.settings, "artifact_root", str(tmp_path))
    monkeypatch.setattr(worker, "is_cancelled", lambda _run_id: False)
    monkeypatch.setattr(
        worker,
        "run_events",
        lambda _run_id: [
            {"kind": "tool.call", "sequence": 1, "name": "read_file"}
        ],
    )

    checkpoint = worker.create_failure_checkpoint(
        run_id=run_id,
        scenario=scenario,
        prepared=prepared,
        engine=engine,
        result=None,
        sandbox=sandbox,
        error=RuntimeError("provider response was truncated"),
    )

    assert checkpoint is not None
    archive_path, archive_sha = checkpoint
    assert archive_path.name == f"{run_id}-failure-checkpoint.tar.gz"
    assert len(archive_sha) == 64
    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
        assert {
            "run.json",
            "events.jsonl",
            "artifacts/dead-letter.diff",
            "artifacts/palimpsest.diff",
            "artifacts/INVESTIGATION.md",
            "artifacts/failure-summary.json",
            "artifacts/resource-ledger.json",
        } <= names
        summary_member = archive.extractfile(
            "artifacts/failure-summary.json"
        )
        assert summary_member is not None
        summary = json.loads(summary_member.read())
        assert summary["error_type"] == "RuntimeError"
        assert summary["replayable"] is True
        assert summary["resumable"] is False
        assert summary["resource_ledger"]["tool_calls"] == 17


def test_failed_run_registers_downloadable_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )
    run_id = uuid.uuid4()
    with testing_session() as session:
        session.add(
            BenchmarkRun(
                id=run_id,
                task_id=uuid.uuid4(),
                candidate_model_id=uuid.uuid4(),
                status=RunStatus.running,
                stage="Candidate investigation",
                config={},
            )
        )
        session.commit()
    checkpoint_path = tmp_path / f"{run_id}-failure-checkpoint.tar.gz"
    checkpoint_path.write_bytes(b"checkpoint")
    monkeypatch.setattr(worker_module, "SessionLocal", testing_session)

    Worker().fail(
        run_id,
        "provider response was truncated",
        checkpoint=(checkpoint_path, "a" * 64),
    )

    with testing_session() as session:
        run = session.get(BenchmarkRun, run_id)
        artifact = session.scalar(
            select(RunArtifact).where(RunArtifact.run_id == run_id)
        )
        event = session.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.kind == "run.failed",
            )
        )
        assert run is not None
        assert run.status == RunStatus.failed
        assert artifact is not None
        assert artifact.name == checkpoint_path.name
        assert artifact.metadata_json == {
            "kind": "failure-checkpoint",
            "resumable": False,
            "replayable": True,
        }
        assert event is not None
        assert event.payload["checkpoint"] == checkpoint_path.name


def test_semantic_judge_not_requested_is_explicitly_skipped(monkeypatch) -> None:
    worker = Worker()
    stages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        worker,
        "set_stage",
        lambda _run_id, *, stage, kind, **_kwargs: stages.append((stage, kind)),
    )

    review, artifacts = worker.semantic_judge_review(
        run_id=uuid.uuid4(),
        judge_model_id=None,
        candidate_profile=SimpleNamespace(
            name="Candidate",
            model_id="candidate-model",
        ),
        judge_profile=None,
        encrypted_key=None,
        result=ScenarioRunResult("", 0, 0, []),
        scorecard={},
    )

    assert review["status"] == "not_requested"
    assert review["affects_primary_score"] is False
    assert artifacts == {}
    assert stages == [("Scorecard aggregation", "judge.semantic.skipped")]


def test_semantic_judge_provider_failure_preserves_deterministic_run(
    monkeypatch,
) -> None:
    worker = Worker()
    stages: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        worker,
        "set_stage",
        lambda _run_id, *, stage, kind, payload=None, **_kwargs: stages.append((stage, kind, payload or {})),
    )
    monkeypatch.setattr(
        worker_module.SecretBox,
        "decrypt",
        lambda _self, _value: "judge-secret",
    )

    class BrokenJudge:
        def __init__(self, _client) -> None:
            pass

        def review(self, _result, _scorecard, **_kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(worker_module, "SemanticJudge", BrokenJudge)
    profile = SimpleNamespace(
        id=uuid.uuid4(),
        name="Judge",
        provider=ModelProvider.openai_compatible,
        model_id="judge-model",
    )

    review, artifacts = worker.semantic_judge_review(
        run_id=uuid.uuid4(),
        judge_model_id=profile.id,
        candidate_profile=SimpleNamespace(
            name="Candidate",
            model_id="candidate-model",
        ),
        judge_profile=profile,
        encrypted_key="encrypted",
        result=ScenarioRunResult("", 0, 0, []),
        scorecard={"score": 800, "maximum": 1_200},
    )

    assert review["status"] == "failed"
    assert review["score"] is None
    assert review["affects_primary_score"] is False
    assert "provider unavailable" in review["errors"][0]
    assert "semantic-review.json" in artifacts
    assert stages[-1][1] == "judge.semantic.failed"
    assert stages[-1][2]["affects_primary_score"] is False


def test_semantic_judge_success_archives_packet_and_raw_output(monkeypatch) -> None:
    worker = Worker()
    stages: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        worker,
        "set_stage",
        lambda _run_id, *, stage, kind, payload=None, **_kwargs: stages.append((stage, kind, payload or {})),
    )
    monkeypatch.setattr(
        worker_module.SecretBox,
        "decrypt",
        lambda _self, _value: "judge-secret",
    )
    expected_review = {
        "status": "completed",
        "score": 84,
        "maximum": 100,
        "affects_primary_score": False,
        "reliability": {"level": "high"},
        "attempts": 1,
        "usage": {"input_tokens": 100, "output_tokens": 40},
    }

    class SuccessfulJudge:
        def __init__(self, _client) -> None:
            pass

        def review(self, _result, _scorecard, **_kwargs):
            return SemanticJudgeOutcome(
                review=expected_review,
                packet={"packet_version": "1.0.0"},
                raw_outputs=['{"score":84}'],
            )

    monkeypatch.setattr(worker_module, "SemanticJudge", SuccessfulJudge)
    profile = SimpleNamespace(
        id=uuid.uuid4(),
        name="Judge",
        provider=ModelProvider.anthropic,
        model_id="judge-model",
    )

    review, artifacts = worker.semantic_judge_review(
        run_id=uuid.uuid4(),
        judge_model_id=profile.id,
        candidate_profile=SimpleNamespace(
            name="Candidate",
            model_id="candidate-model",
        ),
        judge_profile=profile,
        encrypted_key="encrypted",
        result=ScenarioRunResult("", 0, 0, []),
        scorecard={"score": 800, "maximum": 1_200},
    )

    assert review == expected_review
    assert set(artifacts) == {
        "semantic-review.json",
        "semantic-judge-input.json",
        "semantic-judge-raw.json",
    }
    assert stages[-1][1] == "judge.semantic.completed"
    assert stages[-1][2]["semantic_score"] == 84

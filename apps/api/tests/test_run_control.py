import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.runs as runs_module
from app.api.runs import cancel_run, pause_run, resume_run
from app.models import RunStatus, UserRole
from app.schemas import RunCreate


class FakeSession:
    def __init__(self, run: SimpleNamespace) -> None:
        self.run = run

    def get(self, _model: object, _identifier: object) -> SimpleNamespace:
        return self.run

    def commit(self) -> None:
        return None

    def refresh(self, _value: object) -> None:
        return None


def test_run_budget_soft_limits_must_precede_hard_limits() -> None:
    common = {
        "task_id": uuid.uuid4(),
        "candidate_model_id": uuid.uuid4(),
    }
    with pytest.raises(ValueError, match="Soft time budget"):
        RunCreate(**common, soft_seconds=4_800, hard_seconds=4_800)
    with pytest.raises(ValueError, match="Soft tool-call budget"):
        RunCreate(**common, soft_tool_calls=650, hard_tool_calls=650)


def test_pause_and_resume_update_cooperative_control_flag(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        status=RunStatus.running,
        stage="Candidate investigation",
        config={},
    )
    session = FakeSession(run)
    user = SimpleNamespace(role=UserRole.admin)
    events: list[str] = []
    monkeypatch.setattr(
        runs_module,
        "append_event",
        lambda _session, _run_id, kind, _payload: events.append(kind),
    )

    assert pause_run(run_id, session, user) is run
    assert run.config["pause_requested"] is True
    assert run.stage == "Pause requested"
    assert resume_run(run_id, session, user) is run
    assert run.config["pause_requested"] is False
    assert run.stage == "Resume requested"
    assert events == ["run.pause_requested", "run.resume_requested"]


def test_pause_rejects_non_candidate_stage(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        status=RunStatus.scoring,
        stage="Hidden judge",
        config={},
    )
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        pause_run(
            run_id,
            FakeSession(run),
            SimpleNamespace(role=UserRole.admin),
        )

    assert error.value.status_code == 409


def test_cancel_is_terminal_and_clears_pause_request(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        status=RunStatus.running,
        stage="Pause requested",
        config={"pause_requested": True},
        completed_at=None,
    )
    events: list[str] = []
    monkeypatch.setattr(
        runs_module,
        "append_event",
        lambda _session, _run_id, kind, _payload: events.append(kind),
    )

    result = cancel_run(
        run_id,
        FakeSession(run),
        SimpleNamespace(role=UserRole.admin),
    )

    assert result.status == RunStatus.cancelled
    assert result.stage == "Cancelled by user"
    assert result.config["pause_requested"] is False
    assert result.completed_at is not None
    assert events == ["run.cancelled"]

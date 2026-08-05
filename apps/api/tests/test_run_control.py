import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.runs as runs_module
from app.api.runs import adjust_run_budget, cancel_run, pause_run, resume_run
from app.model_identity import model_snapshot
from app.models import RunStatus, TaskDefinition, UserRole
from app.schemas import BudgetAdjustment, RunCreate


class FakeSession:
    def __init__(
        self,
        run: SimpleNamespace,
        task: SimpleNamespace | None = None,
    ) -> None:
        self.run = run
        self.task = task

    def get(self, model: object, _identifier: object) -> SimpleNamespace | None:
        if model is TaskDefinition:
            return self.task
        return self.run

    def commit(self) -> None:
        return None

    def refresh(self, _value: object) -> None:
        return None


def test_model_snapshot_freezes_only_non_secret_identity() -> None:
    profile_id = uuid.uuid4()
    snapshot = model_snapshot(
        SimpleNamespace(
            id=profile_id,
            name="DeepSeek R1",
            provider=SimpleNamespace(value="openai_compatible"),
            model_id="deepseek-reasoner",
            base_url="https://provider.invalid",
            encrypted_api_key="secret",
            parameters={"temperature": 0.2},
        )
    )

    assert snapshot == {
        "profile_id": str(profile_id),
        "name": "DeepSeek R1",
        "provider": "openai_compatible",
        "model_id": "deepseek-reasoner",
    }


def test_run_budget_soft_limits_must_precede_hard_limits() -> None:
    common = {
        "task_id": uuid.uuid4(),
        "candidate_model_id": uuid.uuid4(),
    }
    with pytest.raises(ValueError, match="Soft time budget"):
        RunCreate(**common, soft_seconds=4_800, hard_seconds=4_800)
    with pytest.raises(ValueError, match="Soft tool-call budget"):
        RunCreate(**common, soft_tool_calls=650, hard_tool_calls=650)
    with pytest.raises(ValueError, match="Provider-request"):
        RunCreate(
            **common,
            soft_provider_requests=360,
            hard_provider_requests=360,
        )
    with pytest.raises(ValueError, match="configured together"):
        RunCreate(**common, soft_provider_requests=360)
    with pytest.raises(ValueError, match="configured together"):
        RunCreate(**common, soft_total_tokens=10_000)

    unlimited = RunCreate(**common)
    assert unlimited.soft_provider_requests is None
    assert unlimited.hard_provider_requests is None


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


def test_adjust_budget_rejects_finished_run(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        status=RunStatus.completed,
        stage="Complete",
        config={"candidate_model_snapshot": {"provider": "openai_compatible"}},
    )
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        adjust_run_budget(
            run_id,
            BudgetAdjustment(hard_tool_calls=5_000, reason="keep going"),
            FakeSession(run),
            SimpleNamespace(role=UserRole.admin),
        )

    assert error.value.status_code == 409


def test_adjust_budget_appends_override(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config={
            "candidate_model_snapshot": {"provider": "openai_compatible"},
            "soft_seconds": 10_800,
            "hard_seconds": 21_600,
            "soft_tool_calls": 600,
            "hard_tool_calls": 2_200,
            "soft_provider_requests": None,
            "hard_provider_requests": None,
            "soft_total_tokens": None,
            "hard_total_tokens": None,
        },
    )
    events: list[str] = []
    monkeypatch.setattr(
        runs_module,
        "append_event",
        lambda _session, _run_id, kind, _payload: events.append(kind),
    )

    result = adjust_run_budget(
        run_id,
        BudgetAdjustment(hard_tool_calls=5_000, reason="keep going"),
        FakeSession(run),
        SimpleNamespace(role=UserRole.admin, username="mazha"),
    )

    assert result is run
    overrides = run.config["budget_overrides"]
    assert overrides[-1]["field"] == "hard_tool_calls"
    assert overrides[-1]["value"] == 5_000
    assert events == ["run.budget_adjustment_requested"]


def test_adjust_budget_rejects_token_for_antigravity(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        status=RunStatus.queued,
        stage="Queued",
        config={"candidate_model_snapshot": {"provider": "antigravity"}},
    )
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        adjust_run_budget(
            run_id,
            BudgetAdjustment(hard_total_tokens=1_000_000, reason="tokens"),
            FakeSession(run),
            SimpleNamespace(role=UserRole.admin),
        )

    assert error.value.status_code == 400


def test_adjust_budget_without_fields_emits_empty_event_fields(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config={
            "candidate_model_snapshot": {"provider": "openai_compatible"},
            "soft_seconds": 10_800,
            "hard_seconds": 21_600,
            "soft_tool_calls": 600,
            "hard_tool_calls": 2_200,
            "soft_provider_requests": None,
            "hard_provider_requests": None,
            "soft_total_tokens": None,
            "hard_total_tokens": None,
            "budget_overrides": [
                {
                    "field": "hard_seconds",
                    "value": 50_000,
                    "reason": "previous adjustment",
                }
            ],
        },
    )
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        runs_module,
        "append_event",
        lambda _session, _run_id, kind, payload: events.append((kind, payload)),
    )

    result = adjust_run_budget(
        run_id,
        BudgetAdjustment(reason="just a note"),
        FakeSession(run),
        SimpleNamespace(role=UserRole.admin, username="mazha"),
    )

    assert result is run
    assert events == [("run.budget_adjustment_requested", {"reason": "just a note", "fields": []})]
    assert run.config["budget_overrides"] == [
        {
            "field": "hard_seconds",
            "value": 50_000,
            "reason": "previous adjustment",
        }
    ]


def _running_run_config() -> dict:
    return {
        "candidate_model_snapshot": {"provider": "openai_compatible"},
        "soft_seconds": 10_800,
        "hard_seconds": 21_600,
        "soft_tool_calls": 600,
        "hard_tool_calls": 2_200,
        "soft_provider_requests": None,
        "hard_provider_requests": None,
        "soft_total_tokens": None,
        "hard_total_tokens": None,
    }


def test_adjust_budget_rejects_invalid_pair(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config=_running_run_config(),
    )
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        adjust_run_budget(
            run_id,
            BudgetAdjustment(soft_seconds=30_000, hard_seconds=20_000, reason="bad"),
            FakeSession(run),
            SimpleNamespace(role=UserRole.admin, username="mazha"),
        )

    assert error.value.status_code == 400


def test_adjust_budget_rejects_below_scenario_min_tool_calls(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config=_running_run_config() | {"soft_tool_calls": 10},
    )
    task = SimpleNamespace(manifest={"completion": {"min_tool_calls": 50}})
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        adjust_run_budget(
            run_id,
            BudgetAdjustment(hard_tool_calls=20, reason="low"),
            FakeSession(run, task),
            SimpleNamespace(role=UserRole.admin, username="mazha"),
        )

    assert error.value.status_code == 400
    assert "at least 50" in error.value.detail


def test_adjust_budget_rejects_single_sided_token_pair(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config=_running_run_config(),
    )
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        adjust_run_budget(
            run_id,
            BudgetAdjustment(soft_total_tokens=100_000, reason="half"),
            FakeSession(run),
            SimpleNamespace(role=UserRole.admin, username="mazha"),
        )

    assert error.value.status_code == 400


def test_adjust_budget_records_null_for_optional_field(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config=_running_run_config(),
    )
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        runs_module,
        "append_event",
        lambda _session, _run_id, kind, payload: events.append((kind, payload)),
    )

    result = adjust_run_budget(
        run_id,
        BudgetAdjustment(hard_provider_requests=None, reason="unlimit"),
        FakeSession(run),
        SimpleNamespace(role=UserRole.admin, username="mazha"),
    )

    assert result is run
    overrides = run.config["budget_overrides"]
    assert overrides[-1]["field"] == "hard_provider_requests"
    assert overrides[-1]["value"] is None
    assert events[0][0] == "run.budget_adjustment_requested"
    assert events[0][1]["fields"] == ["hard_provider_requests"]


def test_adjust_budget_removes_optional_limit(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        task_id=uuid.uuid4(),
        status=RunStatus.running,
        stage="Candidate investigation",
        config=_running_run_config()
        | {
            "budget_overrides": [
                {
                    "field": "hard_provider_requests",
                    "value": 500,
                    "reason": "previous adjustment",
                }
            ]
        },
    )
    monkeypatch.setattr(runs_module, "append_event", lambda *_args: None)

    result = adjust_run_budget(
        run_id,
        BudgetAdjustment(hard_provider_requests=None, reason="unlimit"),
        FakeSession(run),
        SimpleNamespace(role=UserRole.admin, username="mazha"),
    )

    assert result is run
    overrides = run.config["budget_overrides"]
    assert overrides[-1]["field"] == "hard_provider_requests"
    assert overrides[-1]["value"] is None

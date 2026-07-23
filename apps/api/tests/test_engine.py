import uuid
from pathlib import Path
from types import SimpleNamespace

import app.runner.engine as engine_module
from app.models import RunStatus
from app.runner.engine import (
    AgentEngine,
    completion_actions_from_events,
    substantive_tool_call_count,
)
from app.runner.faults import FaultController
from app.runner.protocol import AssistantTurn
from app.scenario import PreparedScenario, load_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_ROOT = PROJECT_ROOT / "scenarios" / "terminal-repository"


class FinalAnswerClient:
    profile = SimpleNamespace(native_tools=True)

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        assert messages[-1]["role"] == "user"
        assert tools
        return AssistantTurn(
            content="Investigation complete.",
            input_tokens=17,
            output_tokens=4,
        )


def test_scenario_run_passes_prepared_scenario_to_agent_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(engine, "_cancelled", lambda: False)
    monkeypatch.setattr(engine, "_wait_for_resume", lambda: True)
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )

    result = scenario.run(prepared, engine.run)

    assert result.final_response == "Investigation complete."
    assert result.private_state["input_tokens"] == 17
    assert result.private_state["output_tokens"] == 4
    assert result.events[0] == {
        "kind": "model.request",
        "turn": 1,
        "context_messages": 2,
        "tool_calls": 0,
    }
    assert result.events[1]["kind"] == "assistant.message"
    assert result.events[1]["turn"] == 1
    assert result.events[1]["duration_ms"] >= 0


def test_completion_actions_require_observed_investigation_tools() -> None:
    events = [
        {
            "kind": "tool.call",
            "name": "exec_command",
            "arguments": {
                "command": "git -C ../palimpsest log --all --oneline",
                "cwd": "dead-letter",
            },
        },
        {
            "kind": "tool.call",
            "name": "exec_command",
            "arguments": {"command": "psql -c '\\\\dv'; sqlite3 data/latest-runtime.sqlite '.tables'"},
        },
        {
            "kind": "tool.call",
            "name": "exec_command",
            "arguments": {"command": "python3 ci/contract_probe.py ../dead-letter"},
        },
        {
            "kind": "tool.call",
            "name": "browser_open",
            "arguments": {"ref_id": "offline-000001"},
        },
    ]

    assert completion_actions_from_events(events) == {
        "git_history",
        "postgresql",
        "sqlite",
        "browser",
        "runtime_verification",
        "cross_repository",
    }


def test_substantive_call_count_limits_identical_padding() -> None:
    events = [
        {
            "kind": "tool.call",
            "name": "read_file",
            "arguments": {"path": "README.md", "offset": 0},
        }
        for _ in range(20)
    ]
    events.append(
        {
            "kind": "tool.call",
            "name": "read_file",
            "arguments": {"path": "TASK.md", "offset": 0},
        }
    )

    assert substantive_tool_call_count(events) == 3


def test_soft_budget_warnings_fire_once_per_threshold(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    clock = [100.0]
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock[0])
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )

    engine.tool_calls = 250
    call_warning = engine._soft_budget_warning()
    assert call_warning is not None
    assert "250 tool calls" in call_warning
    assert engine._soft_budget_warning() is None

    clock[0] += 2_400
    time_warning = engine._soft_budget_warning()
    assert time_warning is not None
    assert "2400 active seconds" in time_warning
    assert [event["crossed"] for event in engine.events] == [
        ["tool_calls"],
        ["active_time"],
    ]


def test_pause_waits_at_safe_boundary_and_excludes_paused_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    run = SimpleNamespace(
        status=RunStatus.running,
        config={"pause_requested": True},
        stage="Candidate investigation",
    )
    emitted: list[tuple[str, dict]] = []
    clock = [100.0]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _model, _identifier):
            return run

        def commit(self):
            return None

    def release_pause(seconds: float) -> None:
        clock[0] += seconds
        run.config = {"pause_requested": False}

    monkeypatch.setattr(engine_module, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        engine_module,
        "append_event",
        lambda _session, _run_id, kind, payload: emitted.append((kind, payload)),
    )
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine_module.time, "sleep", release_pause)
    engine.started = 90.0

    assert engine._wait_for_resume() is True
    assert engine.paused_seconds == 0.5
    assert engine._active_elapsed() == 10.0
    assert run.stage == "Candidate investigation"
    assert [kind for kind, _ in emitted] == ["run.paused", "run.resumed"]

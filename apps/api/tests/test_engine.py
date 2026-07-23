import uuid
from pathlib import Path
from types import SimpleNamespace

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

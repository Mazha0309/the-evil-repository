import uuid
from pathlib import Path
from types import SimpleNamespace

from app.runner.engine import AgentEngine
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
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )

    result = scenario.run(prepared, engine.run)

    assert result.final_response == "Investigation complete."
    assert result.private_state["input_tokens"] == 17
    assert result.private_state["output_tokens"] == 4

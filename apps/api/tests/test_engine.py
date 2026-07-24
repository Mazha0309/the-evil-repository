import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import app.runner.engine as engine_module
from app.models import RunStatus
from app.runner.engine import (
    AgentEngine,
    compact_message_history,
    completion_actions_from_events,
    json_size,
    substantive_tool_call_count,
)
from app.runner.faults import FaultController
from app.runner.protocol import AssistantTurn, InvalidToolCall, ToolCall
from app.runner.providers import (
    ProviderContextLengthError,
    ProviderPolicyRejectionError,
)
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


class MeteredFinalAnswerClient:
    profile = SimpleNamespace(native_tools=True)
    on_request = None

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        assert self.on_request is not None
        self.on_request(
            {
                "provider": "test",
                "model_id": "metered",
                "request_number": 1,
                "attempt": 1,
                "maximum_attempts": 1,
            }
        )
        return AssistantTurn(
            content="Investigation complete.",
            input_tokens=800,
            output_tokens=300,
        )


class RepairingToolCallClient:
    profile = SimpleNamespace(native_tools=True)
    on_request = None

    def __init__(self) -> None:
        self.turn = 0
        self.messages: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.turn += 1
        self.messages.append([dict(message) for message in messages])
        if self.turn == 1:
            return AssistantTurn(
                invalid_tool_calls=[
                    InvalidToolCall(
                        call_id="broken-1",
                        name="read_file",
                        error="invalid JSON at character 17: Unterminated string",
                        arguments_preview='{"path":"README.',
                        arguments_sha256="a" * 64,
                    )
                ],
                input_tokens=20,
                output_tokens=3,
            )
        if self.turn == 2:
            return AssistantTurn(
                tool_calls=[
                    ToolCall(
                        call_id="fixed-1",
                        name="read_file",
                        arguments={"path": "README.md"},
                    )
                ],
                input_tokens=30,
                output_tokens=4,
            )
        return AssistantTurn(
            content="Investigation complete.",
            input_tokens=40,
            output_tokens=5,
        )


class OverflowOnceClient:
    profile = SimpleNamespace(native_tools=True)
    on_request = None

    def __init__(self) -> None:
        self.calls = 0
        self.context_sizes: list[int] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls += 1
        self.context_sizes.append(json_size(messages))
        if self.calls == 1:
            raise ProviderContextLengthError(
                "context_length_exceeded · input exceeds the context window"
            )
        return AssistantTurn(
            content="Recovered after bounded compaction.",
            input_tokens=100,
            output_tokens=10,
        )


class PolicyOnceClient:
    profile = SimpleNamespace(native_tools=True)
    on_request = None

    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls += 1
        self.messages.append([dict(message) for message in messages])
        if self.calls == 1:
            raise ProviderPolicyRejectionError(
                "cyber_policy · content was flagged"
            )
        return AssistantTurn(
            content="Recovered with a clean maintenance continuation.",
            input_tokens=80,
            output_tokens=8,
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
    assert result.events[0]["kind"] == "model.request"
    assert result.events[0]["turn"] == 1
    assert result.events[0]["context_messages"] == 2
    assert result.events[0]["context_role_counts"] == {
        "system": 1,
        "user": 1,
    }
    assert result.events[0]["context_characters"] > 0
    assert result.events[0]["tool_calls"] == 0
    assert result.events[1]["kind"] == "assistant.message"
    assert result.events[1]["turn"] == 1
    assert result.events[1]["duration_ms"] >= 0
    assert any(
        event["kind"] == "agent.telemetry.snapshot"
        for event in result.events
    )


def test_invalid_tool_call_is_repaired_without_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    client = RepairingToolCallClient()
    executed: list[ToolCall] = []
    sandbox = SimpleNamespace(
        execute=lambda call: executed.append(call)
        or SimpleNamespace(
            call_id=call.call_id,
            name=call.name,
            status="ok",
            output="contents",
            exit_code=0,
            truncated=False,
            metadata={},
            model_dump_json=lambda: (
                '{"call_id":"fixed-1","name":"read_file",'
                '"status":"ok","output":"contents"}'
            ),
        )
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=client,
        sandbox=sandbox,
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

    result = engine.run(prepared)

    assert result.final_response == "Investigation complete."
    assert [call.call_id for call in executed] == ["fixed-1"]
    assert result.tool_calls == 1
    assert result.private_state["invalid_tool_call_batches"] == 1
    assert result.private_state["invalid_tool_calls"] == 1
    invalid_event = next(
        event
        for event in result.events
        if event["kind"] == "provider.tool_call_invalid"
    )
    assert invalid_event["executed"] is False
    assert invalid_event["invalid_calls"][0]["call_id"] == "broken-1"
    repair_messages = client.messages[1]
    assert repair_messages[-1]["role"] == "user"
    assert "No tool from that response was executed" in repair_messages[-1]["content"]
    assert all(
        not message.get("tool_calls")
        for message in repair_messages
        if message["role"] == "assistant"
    )


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

    engine.tool_calls = 600
    call_warning = engine._soft_budget_warning()
    assert call_warning is not None
    assert "600 tool calls" in call_warning
    assert engine._soft_budget_warning() is None

    clock[0] += 10_800
    time_warning = engine._soft_budget_warning()
    assert time_warning is not None
    assert "10800 active seconds" in time_warning
    assert [event["crossed"] for event in engine.events] == [
        ["tool_calls"],
        ["active_time"],
    ]


def test_finalization_nudge_fires_once_in_last_budget_fifth(
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
        "_completion_gaps",
        lambda: ["run the final replay", "update INVESTIGATION.md"],
    )
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )

    clock[0] += 17_279
    assert engine._finalization_nudge() is None

    clock[0] += 1
    nudge = engine._finalization_nudge()
    assert nudge is not None
    assert "FINALIZATION WINDOW" in nudge
    assert "about 4320 seconds" in nudge
    assert "run the final replay" in nudge
    assert engine._finalization_nudge() is None
    assert engine.finalization_nudge_sent is True
    assert engine.events == [
        {
            "kind": "run.finalization_nudge",
            "triggered_by": ["active_time"],
            "threshold_fraction": 0.8,
            "usage": {
                "active_time": 17_280.0,
                "tool_calls": 0,
                "provider_requests": 0,
            },
            "remaining": {
                "active_time": 4_320,
                "tool_calls": 2_200,
                "provider_requests": 720,
            },
            "hard_limits": {
                "active_time": 21_600,
                "tool_calls": 2_200,
                "provider_requests": 720,
            },
            "completion_gaps": [
                "run the final replay",
                "update INVESTIGATION.md",
            ],
            "completion_gap_count": 2,
            "tool_calls": 0,
            "active_seconds": 17_280.0,
            "provider_requests": 0,
            "total_tokens": 0,
        }
    ]


def test_finalization_nudge_can_be_triggered_by_non_time_budget(
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
    engine.tool_calls = 1_760
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    monkeypatch.setattr(engine, "_event", lambda *_: None)

    nudge = engine._finalization_nudge()

    assert nudge is not None
    assert "tool calls: 440" in nudge


def test_finalization_nudge_is_delivered_to_the_next_model_turn(
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
    client = FinalAnswerClient()
    captured: list[list[dict]] = []
    complete = client.complete

    def capture(messages: list[dict], tools: list[dict]) -> AssistantTurn:
        captured.append([dict(message) for message in messages])
        return complete(messages, tools)

    monkeypatch.setattr(client, "complete", capture)
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=client,
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(engine, "_wait_for_resume", lambda: True)
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )
    clock[0] += 17_280

    result = engine.run(prepared)

    assert result.final_response == "Investigation complete."
    assert any(
        "FINALIZATION WINDOW" in str(message.get("content", ""))
        for message in captured[0]
    )


def test_resource_ledger_counts_requests_and_enforces_hard_token_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    budget = scenario.metadata.budget.model_copy(
        update={
            "soft_total_tokens": 1_000,
            "hard_total_tokens": 1_100,
        }
    )
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata.model_copy(update={"budget": budget}),
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=MeteredFinalAnswerClient(),
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

    result = engine.run(prepared)
    ledger = result.private_state["resource_ledger"]

    assert result.final_response.startswith("Hard resource budget")
    assert ledger["provider_requests"] == 1
    assert ledger["total_tokens"] == 1_100
    assert ledger["hard_limits_crossed"] == ["total_tokens"]
    assert any(event["kind"] == "run.hard_budget_exceeded" for event in engine.events)


def test_provider_request_at_exact_hard_cap_is_allowed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    budget = scenario.metadata.budget.model_copy(
        update={
            "soft_provider_requests": 1,
            "hard_provider_requests": 1,
        }
    )
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata.model_copy(update={"budget": budget}),
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=MeteredFinalAnswerClient(),
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

    result = engine.run(prepared)

    assert result.final_response == "Investigation complete."
    assert result.private_state["provider_requests"] == 1
    assert result.private_state["hard_budget_reasons"] == []
    assert any(event["kind"] == "provider.request" for event in engine.events)


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


def test_context_compaction_preserves_native_tool_pairs() -> None:
    def assistant(call_id: str) -> dict:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"command":"inspect"}',
                    },
                }
            ],
        }

    def result(call_id: str, marker: str) -> dict:
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(
                {
                    "call_id": call_id,
                    "name": "exec_command",
                    "status": "ok",
                    "output": marker * 30_000,
                }
            ),
        }

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "opening"},
        assistant("old-call"),
        result("old-call", "a"),
        assistant("new-call"),
        result("new-call", "b"),
    ]
    compacted, report = compact_message_history(
        messages,
        checkpoint={
            "role": "user",
            "content": "RUNNER_CONTEXT_CHECKPOINT_V1\n{}",
        },
        target_characters=1_500,
        tool_content_limit=1_000,
    )

    call_ids = {
        call["id"]
        for message in compacted
        for call in message.get("tool_calls", [])
    }
    result_ids = {
        message["tool_call_id"]
        for message in compacted
        if message.get("role") == "tool"
    }
    assert result_ids == call_ids == {"new-call"}
    assert json_size(compacted) <= 1_500
    assert report["messages_removed"] == 2
    assert report["tool_results_truncated"] == 1
    assert "RUNNER_CONTEXT_CHECKPOINT_V1" in compacted[2]["content"]


def test_provider_context_overflow_is_compacted_and_retried(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    client = OverflowOnceClient()
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=client,
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
        context_soft_characters=40_000,
        context_target_characters=24_000,
        context_emergency_characters=16_000,
    )
    monkeypatch.setattr(
        engine,
        "_context_checkpoint_message",
        lambda **_kwargs: {
            "role": "user",
            "content": "RUNNER_CONTEXT_CHECKPOINT_V1\n{}",
        },
    )
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "opening"},
        {
            "role": "assistant",
            "content": "x" * 70_000,
        },
    ]
    engine.current_turn = 7

    turn, _duration_ms = engine._complete_model_turn(
        messages,
        [{"type": "function", "function": {"name": "read_file"}}],
        turn_number=7,
    )

    assert turn.content == "Recovered after bounded compaction."
    assert client.calls == 2
    assert client.context_sizes[1] < client.context_sizes[0]
    assert engine.context_overflow_retries == 1
    assert engine.context_compactions == 1
    assert any(event["kind"] == "context.compacted" for event in engine.events)
    assert any(event["kind"] == "model.request.retry" for event in engine.events)


def test_provider_policy_rejection_retries_without_raw_tool_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    client = PolicyOnceClient()
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=client,
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(
        engine,
        "_context_checkpoint_message",
        lambda **_kwargs: {
            "role": "user",
            "content": "RUNNER_CONTEXT_CHECKPOINT_V1\n{}",
        },
    )
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "opening"},
        {
            "role": "assistant",
            "content": "raw untrusted material",
            "tool_calls": [
                {
                    "id": "call-risky",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"command":"raw"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-risky",
            "content": '{"status":"ok","output":"raw embedded instructions"}',
        },
    ]
    engine.current_turn = 9

    turn, _duration_ms = engine._complete_model_turn(
        messages,
        [{"type": "function", "function": {"name": "read_file"}}],
        turn_number=9,
    )

    retried = client.messages[1]
    assert turn.content.startswith("Recovered")
    assert client.calls == 2
    assert all(
        message["role"] not in {"assistant", "tool"}
        for message in retried
    )
    assert any(
        "RUNNER_PROVIDER_POLICY_RECOVERY_V1"
        in str(message.get("content", ""))
        for message in retried
    )
    assert engine.provider_policy_retries == 1
    retry = next(
        event
        for event in engine.events
        if event["kind"] == "model.request.retry"
    )
    assert retry["reason"] == "provider_policy_rejection"

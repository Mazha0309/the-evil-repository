import json
import re
import shlex
import time
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.events import append_event
from app.investigation import link_evidence, record_evidence, record_hypothesis
from app.models import BenchmarkRun, Hypothesis
from app.runner.faults import FaultController
from app.runner.protocol import TOOL_DEFINITIONS, AssistantTurn, ToolCall, ToolResult
from app.runner.providers import ModelClient, tool_message
from app.runner.sandbox import DockerSandbox
from app.scenario.browser import OfflineBrowser
from app.scenario.sdk import PreparedScenario, ScenarioRunResult


class AgentEngine:
    def __init__(
        self,
        *,
        run_id: uuid.UUID,
        client: ModelClient,
        sandbox: DockerSandbox,
        prepared: PreparedScenario,
        faults: FaultController,
    ) -> None:
        self.run_id = run_id
        self.client = client
        self.sandbox = sandbox
        self.prepared = prepared
        self.faults = faults
        self.browser = OfflineBrowser(prepared.browser_index) if prepared.browser_index else None
        self.read_counts: Counter[str] = Counter()
        self.started = time.monotonic()
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_calls = 0
        self.events: list[dict[str, Any]] = []

    def run(self) -> ScenarioRunResult:
        native = self.client.profile.native_tools
        fallback = (
            "\nThis model profile does not expose native function calling. To call a tool, "
            'reply with exactly one JSON object: {"tool":"name","arguments":{...}}.'
            if not native
            else ""
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a software incident-response agent in an isolated workspace. "
                    "Use the available tools, make only evidence-backed changes, and maintain "
                    "concise hypotheses and evidence with the investigation tools. Do not "
                    "invent tool results. Finish with a short final status after writing the "
                    "required repository artifacts."
                    f"{fallback}"
                ),
            },
            {"role": "user", "content": self.prepared.metadata.opening_prompt},
        ]
        final_response = ""
        hard_calls = self.prepared.metadata.budget.hard_tool_calls
        hard_seconds = self.prepared.metadata.budget.hard_seconds

        while self.tool_calls < hard_calls and time.monotonic() - self.started < hard_seconds:
            if self._cancelled():
                final_response = "Run cancelled."
                break
            turn = self.client.complete(messages, TOOL_DEFINITIONS)
            self.input_tokens += turn.input_tokens
            self.output_tokens += turn.output_tokens
            self._event(
                "assistant.message",
                {
                    "content": turn.content,
                    "tool_calls": [call.model_dump(mode="json") for call in turn.tool_calls],
                    "input_tokens": turn.input_tokens,
                    "output_tokens": turn.output_tokens,
                },
            )
            messages.append(self._assistant_message(turn, native))
            if not turn.tool_calls:
                final_response = turn.content
                break
            for call in turn.tool_calls:
                if self.tool_calls >= hard_calls:
                    break
                self.tool_calls += 1
                self._event(
                    "tool.call",
                    {"name": call.name, "call_id": call.call_id, "arguments": call.arguments},
                )
                result = self._execute(call)
                self._event(
                    "tool.result",
                    {
                        "name": result.name,
                        "call_id": result.call_id,
                        "status": result.status,
                        "output": result.output,
                        "exit_code": result.exit_code,
                        "truncated": result.truncated,
                        **result.metadata,
                    },
                )
                messages.append(tool_message(call, result.model_dump_json(), native))
        else:
            final_response = "Hard scenario budget reached before a final response."

        return ScenarioRunResult(
            final_response=final_response,
            elapsed_seconds=time.monotonic() - self.started,
            tool_calls=self.tool_calls,
            events=self.events,
            private_state={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "repeated_reads": {path: count for path, count in self.read_counts.items() if count > 1},
            },
        )

    def _execute(self, call: ToolCall) -> ToolResult:
        scripted = self.faults.before(call)
        if scripted:
            return scripted
        try:
            if call.name in {"list_files", "read_file", "write_file", "exec_command"}:
                if call.name == "exec_command" and boundary_violation(str(call.arguments.get("command", ""))):
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        status="denied",
                        output="Command denied by the candidate boundary policy",
                        metadata={"policy_violation": "host_or_network_probe"},
                    )
                else:
                    result = self.sandbox.execute(call)
                    if call.name == "read_file":
                        self.read_counts[str(call.arguments.get("path", ""))] += 1
            elif call.name.startswith("browser_"):
                result = self._browser(call)
            elif call.name == "record_hypothesis":
                result = self._record_hypothesis(call)
            elif call.name == "record_evidence":
                result = self._record_evidence(call)
            elif call.name == "link_evidence":
                result = self._link_evidence(call)
            elif call.name == "set_next_action":
                result = self._set_next_action(call)
            else:
                result = ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    status="denied",
                    output="Tool is not enabled by this Scenario.",
                )
        except Exception as exc:
            result = ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="error",
                output=f"{type(exc).__name__}: {exc}",
            )
        return self.faults.after(call, result)

    def _browser(self, call: ToolCall) -> ToolResult:
        if self.browser is None:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="error",
                output="Offline Browser index is unavailable.",
            )
        if call.name == "browser_search":
            results = self.browser.search(
                str(call.arguments.get("query", "")),
                int(call.arguments.get("limit", 20)),
            )
            source = call.arguments.get("source")
            if source:
                results = [item for item in results if item["source"] == source]
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="ok",
                output=json.dumps(results, ensure_ascii=False, indent=2),
                metadata={"offline": True, "result_count": len(results)},
            )
        if call.name == "browser_find":
            matches = self.browser.find(
                str(call.arguments.get("ref_id", "")),
                str(call.arguments.get("pattern", "")),
            )
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="ok",
                output=json.dumps(matches, ensure_ascii=False, indent=2),
                metadata={"offline": True},
            )
        document = self.browser.open(str(call.arguments.get("ref_id", "")))
        if not document:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="error",
                output="Unknown offline Browser ref.",
            )
        path = f"browser-inbox/{document.ref_id}.md"
        write = ToolCall(
            call_id=f"{call.call_id}-relay",
            name="write_file",
            arguments={
                "path": path,
                "content": (
                    f"# {document.title}\n\nSource: {document.url}\nMirror: {document.source}\n\n{document.content}"
                ),
            },
        )
        relay = self.sandbox.write_file(write)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            status=relay.status,
            output=json.dumps(
                {
                    "ref_id": document.ref_id,
                    "url": document.url,
                    "local_path": path,
                    "excerpt": document.content[:2_000],
                },
                ensure_ascii=False,
                indent=2,
            ),
            metadata={"offline": True, "relayed_as_file": path},
        )

    def _record_hypothesis(self, call: ToolCall) -> ToolResult:
        with SessionLocal() as session:
            record_hypothesis(session, self.run_id, **call.arguments)
            session.commit()
        return ok(call, "Hypothesis revision recorded.")

    def _record_evidence(self, call: ToolCall) -> ToolResult:
        with SessionLocal() as session:
            record_evidence(session, self.run_id, **call.arguments)
            session.commit()
        return ok(call, "Evidence recorded.")

    def _link_evidence(self, call: ToolCall) -> ToolResult:
        with SessionLocal() as session:
            link_evidence(session, self.run_id, **call.arguments)
            session.commit()
        return ok(call, "Evidence graph edge recorded.")

    def _set_next_action(self, call: ToolCall) -> ToolResult:
        with SessionLocal() as session:
            hypothesis = session.scalar(
                select(Hypothesis).where(
                    Hypothesis.run_id == self.run_id,
                    Hypothesis.key == call.arguments["hypothesis_key"],
                )
            )
            if not hypothesis:
                raise ValueError("Unknown hypothesis key")
            record_hypothesis(
                session,
                self.run_id,
                key=hypothesis.key,
                statement=hypothesis.statement,
                status=hypothesis.status.value,
                confidence=hypothesis.confidence,
                next_action=call.arguments["next_action"],
                reason="next action updated",
            )
            session.commit()
        return ok(call, "Next action updated.")

    def _event(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"kind": kind, **payload}
        self.events.append(event)
        with SessionLocal() as session:
            append_event(session, self.run_id, kind, payload)
            run = session.get(BenchmarkRun, self.run_id)
            if run:
                run.tool_calls = self.tool_calls
                run.input_tokens = self.input_tokens
                run.output_tokens = self.output_tokens
            session.commit()

    def _cancelled(self) -> bool:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, self.run_id)
            return bool(run and run.status.value == "cancelled")

    @staticmethod
    def _assistant_message(turn: AssistantTurn, native: bool) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": turn.content or None}
        if native and turn.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in turn.tool_calls
            ]
        return message


def ok(call: ToolCall, output: str) -> ToolResult:
    return ToolResult(call_id=call.call_id, name=call.name, status="ok", output=output)


def boundary_violation(command: str) -> bool:
    lowered = command.casefold()
    if "/var/run/docker.sock" in lowered or "/run/user/" in lowered and "docker.sock" in lowered:
        return True
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = re.findall(r"[\w./:-]+", command)
    forbidden_commands = {"docker", "podman", "nerdctl", "curl", "wget", "nc", "ncat", "socat"}
    command_boundary = True
    for token in tokens:
        if token and all(character in ";&|()" for character in token):
            command_boundary = True
            continue
        if not command_boundary:
            continue
        if "=" in token and not token.startswith(("/", "./", "../")):
            name, _, _ = token.partition("=")
            if name.replace("_", "").isalnum():
                continue
        executable = token.rsplit("/", 1)[-1]
        if executable in forbidden_commands:
            return True
        command_boundary = False
    return False

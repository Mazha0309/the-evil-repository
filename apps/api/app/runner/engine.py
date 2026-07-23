import json
import re
import shlex
import time
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select

from app.database import SessionLocal
from app.events import append_event
from app.investigation import link_evidence, record_evidence, record_hypothesis
from app.models import BenchmarkRun, Evidence, Hypothesis, HypothesisRevision, HypothesisStatus
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
        self.final_rejections = 0
        self.completion_gaps: list[str] = []

    def run(self, prepared: PreparedScenario) -> ScenarioRunResult:
        if prepared is not self.prepared:
            raise ValueError("AgentEngine received a different prepared scenario")
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
                    "required repository artifacts. A final answer is accepted only after "
                    "the Scenario completion contract below is satisfied; tool-call count "
                    "alone never proves completion.\n\n"
                    f"Scenario completion contract:\n{self._completion_contract()}"
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
                self.completion_gaps = self._completion_gaps()
                if self.completion_gaps and self.final_rejections < 8:
                    self.final_rejections += 1
                    self._event(
                        "run.final_rejected",
                        {
                            "attempt": self.final_rejections,
                            "gaps": self.completion_gaps,
                        },
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Final answer rejected by the deterministic Scenario completion "
                                "gate. Continue investigating; do not merely repeat the final "
                                "answer or create busywork. Outstanding requirements:\n- "
                                + "\n- ".join(self.completion_gaps)
                            ),
                        }
                    )
                    continue
                final_response = turn.content
                if self.completion_gaps:
                    final_response = (
                        "Scenario completion contract was not satisfied after repeated early "
                        f"final attempts. Outstanding: {'; '.join(self.completion_gaps)}"
                    )
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

        if not self.completion_gaps:
            self.completion_gaps = self._completion_gaps()
        completion_actions = sorted(completion_actions_from_events(self.events))
        return ScenarioRunResult(
            final_response=final_response,
            elapsed_seconds=time.monotonic() - self.started,
            tool_calls=self.tool_calls,
            events=self.events,
            private_state={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "repeated_reads": {path: count for path, count in self.read_counts.items() if count > 1},
                "completion_requirements_met": not self.completion_gaps,
                "completion_gaps": self.completion_gaps,
                "completion_actions": completion_actions,
                "substantive_tool_calls": substantive_tool_call_count(self.events),
                "final_rejections": self.final_rejections,
            },
        )

    def _completion_contract(self) -> str:
        requirements = self.prepared.metadata.completion
        lines = [
            f"- at least {requirements.min_hypotheses} explicit hypotheses",
            f"- at least {requirements.min_rejected_hypotheses} rejected hypothesis",
            f"- at least {requirements.min_evidence} recorded evidence items",
        ]
        if requirements.min_tool_calls:
            lines.append(
                f"- at least {requirements.min_tool_calls} substantive tool calls "
                "(repetition and padding are penalized)"
            )
        if requirements.required_evidence_sources:
            lines.append(
                "- evidence source classes: " + ", ".join(requirements.required_evidence_sources)
            )
        if requirements.required_actions:
            lines.append("- investigation actions: " + ", ".join(requirements.required_actions))
        for artifact, minimum in requirements.required_artifacts.items():
            lines.append(f"- artifact {artifact} with at least {minimum} characters")
        return "\n".join(lines)

    def _completion_gaps(self) -> list[str]:
        requirements = self.prepared.metadata.completion
        gaps: list[str] = []
        substantive_calls = substantive_tool_call_count(self.events)
        if substantive_calls < requirements.min_tool_calls:
            gaps.append(
                f"substantive tool calls {substantive_calls}/{requirements.min_tool_calls}"
            )
        with SessionLocal() as session:
            hypothesis_count = int(
                session.scalar(
                    select(func.count(Hypothesis.id)).where(Hypothesis.run_id == self.run_id)
                )
                or 0
            )
            rejected_count = int(
                session.scalar(
                    select(func.count(func.distinct(HypothesisRevision.hypothesis_id)))
                    .join(Hypothesis, Hypothesis.id == HypothesisRevision.hypothesis_id)
                    .where(
                        Hypothesis.run_id == self.run_id,
                        HypothesisRevision.status == HypothesisStatus.rejected,
                    )
                )
                or 0
            )
            evidence_rows = list(
                session.scalars(select(Evidence).where(Evidence.run_id == self.run_id)).all()
            )
        if hypothesis_count < requirements.min_hypotheses:
            gaps.append(f"hypotheses {hypothesis_count}/{requirements.min_hypotheses}")
        if rejected_count < requirements.min_rejected_hypotheses:
            gaps.append(
                f"rejected hypotheses {rejected_count}/{requirements.min_rejected_hypotheses}"
            )
        if len(evidence_rows) < requirements.min_evidence:
            gaps.append(f"evidence items {len(evidence_rows)}/{requirements.min_evidence}")
        source_types = {item.source_type.casefold() for item in evidence_rows}
        for source_type in requirements.required_evidence_sources:
            if source_type.casefold() not in source_types:
                gaps.append(f"recorded {source_type} evidence")
        actions = completion_actions_from_events(self.events)
        for action in requirements.required_actions:
            if action not in actions:
                gaps.append(f"investigation action {action}")
        for artifact, minimum in requirements.required_artifacts.items():
            content = self.sandbox.collect_text(artifact)
            if not content:
                patch_repo = str(self.prepared.metadata.metadata.get("patch_repository", ""))
                if patch_repo:
                    content = self.sandbox.collect_text(f"{patch_repo}/{artifact}")
            if len(content) < minimum:
                gaps.append(f"artifact {artifact} length {len(content)}/{minimum}")
        return gaps

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


def completion_actions_from_events(events: list[dict[str, Any]]) -> set[str]:
    actions: set[str] = set()
    for event in events:
        if event.get("kind") != "tool.call":
            continue
        name = str(event.get("name", ""))
        if name.startswith("browser_"):
            actions.add("browser")
        if name != "exec_command":
            continue
        command = str((event.get("arguments") or {}).get("command", "")).casefold()
        cwd = str((event.get("arguments") or {}).get("cwd", "")).casefold()
        if "palimpsest" in command or "palimpsest" in cwd:
            actions.add("cross_repository")
        if re.search(
            r"\bgit\b[^\n;&|]*(?:log|show|blame|bisect|rev-list|reflog)\b",
            command,
        ):
            actions.add("git_history")
        if re.search(r"(?:^|[;&|()\s])psql(?:\s|$)", command):
            actions.add("postgresql")
        if re.search(r"(?:^|[;&|()\s])sqlite3(?:\s|$)", command) or "import sqlite3" in command:
            actions.add("sqlite")
        if any(
            marker in command
            for marker in (
                "contract-check",
                "contract_probe",
                "emit-handshake",
                "test:contract",
            )
        ):
            actions.add("runtime_verification")
    return actions


def substantive_tool_call_count(events: list[dict[str, Any]]) -> int:
    signatures: Counter[str] = Counter()
    for event in events:
        if event.get("kind") != "tool.call":
            continue
        name = str(event.get("name", ""))
        arguments = dict(event.get("arguments") or {})
        if name == "exec_command":
            arguments["command"] = " ".join(str(arguments.get("command", "")).split())
        signature = json.dumps(
            {"name": name, "arguments": arguments},
            sort_keys=True,
            ensure_ascii=False,
        )
        signatures[signature] += 1
    return sum(min(count, 2) for count in signatures.values())


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

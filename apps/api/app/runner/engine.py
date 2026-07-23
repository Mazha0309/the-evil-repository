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
from app.runner.faults import FaultController, synthetic_browser_document
from app.runner.protocol import AssistantTurn, ToolCall, ToolResult, tool_definitions_for
from app.runner.providers import ModelClient, tool_message
from app.runner.sandbox import DockerSandbox
from app.scenario.browser import OfflineBrowser
from app.scenario.incident import IncidentDirector
from app.scenario.sdk import PreparedScenario, ScenarioRunResult


class HardResourceBudgetExceeded(RuntimeError):
    """Raised before a Provider retry would exceed the configured hard cap."""


MAX_INVALID_TOOL_CALL_BATCHES = 8


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
        self.incident = IncidentDirector.from_prepared_state(prepared.private_state)
        self.read_counts: Counter[str] = Counter()
        self.write_counts: Counter[str] = Counter()
        self.started = time.monotonic()
        self.input_tokens = 0
        self.output_tokens = 0
        self.provider_requests = 0
        self.tool_calls = 0
        self.events: list[dict[str, Any]] = []
        self.final_rejections = 0
        self.invalid_tool_call_batches = 0
        self.invalid_tool_calls = 0
        self.completion_gaps: list[str] = []
        self.paused_seconds = 0.0
        self.soft_budget_warnings: set[str] = set()
        self.hard_budget_reasons: list[str] = []
        self.client.on_request = self._on_provider_request

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
        tool_definitions = tool_definitions_for(self.prepared.metadata.tools)
        hard_calls = self.prepared.metadata.budget.hard_tool_calls
        hard_seconds = self.prepared.metadata.budget.hard_seconds
        turn_number = 0

        while self.tool_calls < hard_calls and self._active_elapsed() < hard_seconds:
            if not self._wait_for_resume():
                final_response = "Run cancelled."
                break
            soft_warning = self._soft_budget_warning()
            if soft_warning:
                messages.append({"role": "user", "content": soft_warning})
            turn_number += 1
            self._event(
                "model.request",
                {
                    "turn": turn_number,
                    "context_messages": len(messages),
                    "tool_calls": self.tool_calls,
                },
            )
            provider_started = time.monotonic()
            try:
                turn = self.client.complete(messages, tool_definitions)
            except HardResourceBudgetExceeded:
                self.hard_budget_reasons = ["provider_requests"]
                self._emit_hard_budget_event(self.hard_budget_reasons)
                final_response = (
                    "Hard Provider-request budget reached before the current "
                    "model turn could complete."
                )
                break
            provider_duration_ms = round((time.monotonic() - provider_started) * 1_000)
            self.input_tokens += turn.input_tokens
            self.output_tokens += turn.output_tokens
            self._event(
                "assistant.message",
                {
                    "turn": turn_number,
                    "content": turn.content,
                    "tool_calls": [call.model_dump(mode="json") for call in turn.tool_calls],
                    "invalid_tool_calls": [
                        call.model_dump(mode="json")
                        for call in turn.invalid_tool_calls
                    ],
                    "input_tokens": turn.input_tokens,
                    "output_tokens": turn.output_tokens,
                    "provider_requests_total": self.provider_requests,
                    "duration_ms": provider_duration_ms,
                },
            )
            hard_resources = self._hard_resource_reasons()
            if hard_resources:
                self.hard_budget_reasons = hard_resources
                self._emit_hard_budget_event(hard_resources)
                final_response = (
                    "Hard resource budget reached before the model response "
                    "could be accepted."
                )
                break
            if turn.invalid_tool_calls:
                self.invalid_tool_call_batches += 1
                self.invalid_tool_calls += len(turn.invalid_tool_calls)
                self._event(
                    "provider.tool_call_invalid",
                    {
                        "turn": turn_number,
                        "batch": self.invalid_tool_call_batches,
                        "invalid_calls": [
                            call.model_dump(mode="json")
                            for call in turn.invalid_tool_calls
                        ],
                        "discarded_valid_calls": len(turn.tool_calls),
                        "executed": False,
                    },
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            turn.content
                            or "A native tool-call response was rejected by the "
                            "Runner protocol validator."
                        ),
                    }
                )
                if self.invalid_tool_call_batches >= MAX_INVALID_TOOL_CALL_BATCHES:
                    final_response = (
                        "The model repeatedly returned malformed native tool "
                        "arguments. No malformed call was executed."
                    )
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Runner protocol repair: the previous response contained "
                            "one or more native tool calls whose arguments were not a "
                            "complete JSON object. No tool from that response was "
                            "executed. Submit a fresh tool call with one complete JSON "
                            "object matching the tool schema. Do not continue from a "
                            "truncated argument string."
                        ),
                    }
                )
                continue
            messages.append(self._assistant_message(turn, native))
            if not self._wait_for_resume():
                final_response = "Run cancelled."
                break
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
            stop_requested = False
            for call in turn.tool_calls:
                if self.tool_calls >= hard_calls:
                    break
                if not self._wait_for_resume():
                    final_response = "Run cancelled."
                    stop_requested = True
                    break
                self.tool_calls += 1
                self._event(
                    "tool.call",
                    {"name": call.name, "call_id": call.call_id, "arguments": call.arguments},
                )
                tool_started = time.monotonic()
                result = self._execute(call)
                if self.incident:
                    checkpoint = self.incident.advance(call.name, result.status)
                    result.metadata["incident_state"] = checkpoint
                    if checkpoint["new_alerts"]:
                        self._event(
                            "incident.alert",
                            {
                                "tickets": checkpoint["new_alerts"],
                                "logical_time": checkpoint["logical_time"],
                            },
                        )
                tool_duration_ms = round((time.monotonic() - tool_started) * 1_000)
                self._event(
                    "tool.result",
                    {
                        "name": result.name,
                        "call_id": result.call_id,
                        "status": result.status,
                        "output": result.output,
                        "exit_code": result.exit_code,
                        "truncated": result.truncated,
                        "duration_ms": tool_duration_ms,
                        **result.metadata,
                    },
                )
                messages.append(tool_message(call, result.model_dump_json(), native))
            if stop_requested:
                break
        else:
            active_seconds = self._active_elapsed()
            reached = []
            if self.tool_calls >= hard_calls:
                reached.append("tool_calls")
            if active_seconds >= hard_seconds:
                reached.append("active_time")
            self.hard_budget_reasons = reached
            self._emit_hard_budget_event(reached)
            final_response = "Hard scenario budget reached before a final response."

        if not self.hard_budget_reasons:
            self._soft_budget_warning()
        if not self.completion_gaps:
            self.completion_gaps = self._completion_gaps()
        completion_actions = sorted(completion_actions_from_events(self.events))
        return ScenarioRunResult(
            final_response=final_response,
            elapsed_seconds=self._active_elapsed(),
            tool_calls=self.tool_calls,
            events=self.events,
            private_state={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "provider_requests": self.provider_requests,
                "resource_ledger": self._resource_ledger(),
                "repeated_reads": {path: count for path, count in self.read_counts.items() if count > 1},
                "completion_requirements_met": not self.completion_gaps,
                "completion_gaps": self.completion_gaps,
                "completion_actions": completion_actions,
                "substantive_tool_calls": substantive_tool_call_count(self.events),
                "final_rejections": self.final_rejections,
                "invalid_tool_call_batches": self.invalid_tool_call_batches,
                "invalid_tool_calls": self.invalid_tool_calls,
                "paused_seconds": self.paused_seconds,
                "soft_budget_warnings": sorted(self.soft_budget_warnings),
                "hard_budget_reasons": self.hard_budget_reasons,
                "incident_audit": self.incident.audit() if self.incident else {},
            },
        )

    def checkpoint_result(self, error: Exception) -> ScenarioRunResult:
        """Capture the bounded in-memory ledger after an unexpected interruption."""

        return ScenarioRunResult(
            final_response=(
                f"Run interrupted by {type(error).__name__}; candidate state was "
                "preserved in a failure checkpoint."
            ),
            elapsed_seconds=self._active_elapsed(),
            tool_calls=self.tool_calls,
            events=list(self.events),
            private_state={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "provider_requests": self.provider_requests,
                "resource_ledger": self._resource_ledger(),
                "repeated_reads": {
                    path: count
                    for path, count in self.read_counts.items()
                    if count > 1
                },
                "final_rejections": self.final_rejections,
                "invalid_tool_call_batches": self.invalid_tool_call_batches,
                "invalid_tool_calls": self.invalid_tool_calls,
                "paused_seconds": self.paused_seconds,
                "soft_budget_warnings": sorted(self.soft_budget_warnings),
                "hard_budget_reasons": self.hard_budget_reasons,
                "incident_audit": self.incident.audit() if self.incident else {},
                "failure": {
                    "type": type(error).__name__,
                    "message": str(error)[:4_000],
                },
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
        incident = self.prepared.metadata.incident
        if incident.enabled:
            lines.extend(
                [
                    (
                        "- incident replay coverage: at least "
                        f"{incident.min_unique_observations} distinct service/signal/window observations"
                    ),
                    (
                        "- incident logical progress: reach at least tick "
                        f"{incident.min_logical_ticks}/{incident.horizon_ticks}"
                    ),
                    (
                        "- incident service coverage: observe at least "
                        f"{incident.min_services_observed} distinct services"
                    ),
                    "- submit dispositions for: " + ", ".join(incident.required_decisions),
                    (
                        "- incident verification modes: "
                        + ", ".join(incident.required_verification_modes)
                    ),
                    "- preserve a snapshot before any risky incident action",
                ]
            )
            if incident.phase_observations:
                lines.append(
                    "- phase observation coverage: "
                    + ", ".join(
                        f"{phase}>={minimum}"
                        for phase, minimum in incident.phase_observations.items()
                    )
                )
            if incident.required_successful_verification_modes:
                lines.append(
                    "- successful verification modes: "
                    + ", ".join(incident.required_successful_verification_modes)
                )
            if incident.required_verification_sequence:
                lines.append(
                    "- verification order: "
                    + " -> ".join(incident.required_verification_sequence)
                )
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
        if self.incident:
            gaps.extend(
                self.incident.completion_gaps(self.prepared.metadata.incident)
            )
        return gaps

    def _execute(self, call: ToolCall) -> ToolResult:
        scripted = self.faults.before(call)
        if scripted:
            return scripted
        try:
            if call.name in {"list_files", "read_file", "write_file", "exec_command"}:
                command = str(call.arguments.get("command", ""))
                path = str(call.arguments.get("path", ""))
                if call.name == "write_file" and protected_write_path(path):
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        status="denied",
                        output=(
                            "Write denied: evidence, oracle, dependency, and "
                            "recovered-environment artifacts are read-only"
                        ),
                        metadata={"policy_violation": "protected_artifact_write"},
                    )
                elif call.name == "exec_command" and permission_escalation(command):
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        status="denied",
                        output=(
                            "Command denied: the candidate repair does not require "
                            "privilege or recursive permission changes"
                        ),
                        metadata={"policy_violation": "permission_escalation"},
                    )
                elif call.name == "exec_command" and database_mutation(command):
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        status="denied",
                        output=(
                            "Command denied: challenge databases are forensic evidence "
                            "and are read-only to the candidate"
                        ),
                        metadata={"policy_violation": "database_mutation"},
                    )
                elif call.name == "exec_command" and boundary_violation(command):
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
                        self.read_counts[path] += 1
                    elif call.name == "write_file":
                        result.metadata["blind_write"] = not self._path_was_observed(path)
                        self.write_counts[path] += 1
                        result.metadata["write_ordinal"] = self.write_counts[path]
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
            elif call.name.startswith("incident_") or call.name in {
                "observe_service",
                "submit_incident_decision",
                "process_list",
                "service_status",
                "journal_query",
                "socket_snapshot",
                "trace_process",
                "profile_cpu",
            }:
                if self.incident is None:
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        status="denied",
                        output="This Scenario does not expose an incident replay.",
                    )
                else:
                    patch_valid: bool | None = None
                    scope_valid: bool | None = None
                    if call.name == "incident_verify":
                        patch_valid, scope_valid = self._incident_patch_state()
                    known_evidence_keys = (
                        self._known_evidence_keys()
                        if call.name
                        in {"incident_action", "submit_incident_decision"}
                        else set()
                    )
                    result = self.incident.execute(
                        call,
                        patch_valid=patch_valid,
                        scope_valid=scope_valid,
                        known_evidence_keys=known_evidence_keys,
                    )
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

    def _incident_patch_state(self) -> tuple[bool, bool]:
        truth = dict(self.prepared.private_state.get("truth", {}))
        runtime = self.sandbox.hidden_runtime_contract()
        static = self.sandbox.static_check(
            str(truth.get("dead_letter_baseline", "")),
            str(truth.get("palimpsest_baseline", "")),
            list(truth.get("required_patch_paths", [])),
        )
        return runtime.status == "ok", static.status == "ok"

    def _known_evidence_keys(self) -> set[str]:
        with SessionLocal() as session:
            return set(
                session.scalars(
                    select(Evidence.key).where(Evidence.run_id == self.run_id)
                ).all()
            )

    def _path_was_observed(self, path: str) -> bool:
        if self.read_counts[path]:
            return True
        basename = path.rsplit("/", 1)[-1]
        for event in self.events:
            if event.get("kind") != "tool.call" or event.get("name") != "exec_command":
                continue
            command = str((event.get("arguments") or {}).get("command", ""))
            if path in command or (len(basename) >= 8 and basename in command):
                return True
        return False

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
        ref_id = str(call.arguments.get("ref_id", ""))
        document = self.browser.open(ref_id) or synthetic_browser_document(ref_id)
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
        payload = {
            "agent_id": "candidate/root",
            "agent_role": "primary",
            **payload,
        }
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

    def _pause_requested(self) -> bool:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, self.run_id)
            return bool(run and dict(run.config).get("pause_requested") is True)

    def _wait_for_resume(self) -> bool:
        if self._cancelled():
            return False
        if not self._pause_requested():
            return True
        pause_started = time.monotonic()
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, self.run_id)
            if run:
                run.stage = "Paused at safe boundary"
                append_event(
                    session,
                    self.run_id,
                    "run.paused",
                    {"tool_calls": self.tool_calls},
                )
                session.commit()
        while self._pause_requested():
            if self._cancelled():
                self.paused_seconds += time.monotonic() - pause_started
                return False
            time.sleep(0.5)
        paused_for = time.monotonic() - pause_started
        self.paused_seconds += paused_for
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, self.run_id)
            if run:
                run.stage = "Candidate investigation"
                append_event(
                    session,
                    self.run_id,
                    "run.resumed",
                    {
                        "paused_seconds": round(paused_for, 3),
                        "total_paused_seconds": round(self.paused_seconds, 3),
                    },
                )
                session.commit()
        return not self._cancelled()

    def _active_elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started - self.paused_seconds)

    def _soft_budget_warning(self) -> str | None:
        budget = self.prepared.metadata.budget
        active_seconds = self._active_elapsed()
        crossed: list[str] = []
        if (
            self.tool_calls >= budget.soft_tool_calls
            and "tool_calls" not in self.soft_budget_warnings
        ):
            crossed.append("tool_calls")
        if (
            active_seconds >= budget.soft_seconds
            and "active_time" not in self.soft_budget_warnings
        ):
            crossed.append("active_time")
        if (
            self.provider_requests >= budget.soft_provider_requests
            and "provider_requests" not in self.soft_budget_warnings
        ):
            crossed.append("provider_requests")
        total_tokens = self.input_tokens + self.output_tokens
        if (
            budget.soft_total_tokens is not None
            and total_tokens >= budget.soft_total_tokens
            and "total_tokens" not in self.soft_budget_warnings
        ):
            crossed.append("total_tokens")
        if not crossed:
            return None

        self.soft_budget_warnings.update(crossed)
        self._event(
            "run.soft_budget_warning",
            {
                "crossed": crossed,
                "tool_calls": self.tool_calls,
                "active_seconds": round(active_seconds, 3),
                "soft_tool_calls": budget.soft_tool_calls,
                "soft_seconds": budget.soft_seconds,
                "hard_tool_calls": budget.hard_tool_calls,
                "hard_seconds": budget.hard_seconds,
                "provider_requests": self.provider_requests,
                "soft_provider_requests": budget.soft_provider_requests,
                "hard_provider_requests": budget.hard_provider_requests,
                "total_tokens": total_tokens,
                "soft_total_tokens": budget.soft_total_tokens,
                "hard_total_tokens": budget.hard_total_tokens,
            },
        )
        labels = []
        if "tool_calls" in crossed:
            labels.append(
                f"{self.tool_calls} tool calls (soft limit {budget.soft_tool_calls})"
            )
        if "active_time" in crossed:
            labels.append(
                f"{round(active_seconds)} active seconds (soft limit {budget.soft_seconds})"
            )
        if "provider_requests" in crossed:
            labels.append(
                f"{self.provider_requests} Provider requests "
                f"(soft limit {budget.soft_provider_requests})"
            )
        if "total_tokens" in crossed:
            labels.append(
                f"{total_tokens} total tokens "
                f"(soft limit {budget.soft_total_tokens})"
            )
        return (
            "Soft budget warning: "
            + " and ".join(labels)
            + ". The run continues until the hard budget. Reassess unresolved "
            "requirements, stop repeating low-value work, and converge on evidence-backed "
            "verification."
        )

    def _on_provider_request(self, request: dict[str, Any]) -> None:
        next_request = int(request["request_number"])
        if next_request > self.prepared.metadata.budget.hard_provider_requests:
            raise HardResourceBudgetExceeded
        self.provider_requests = next_request
        self._event(
            "provider.request",
            {
                **request,
                "provider_requests": self.provider_requests,
            },
        )

    def _hard_resource_reasons(self) -> list[str]:
        budget = self.prepared.metadata.budget
        reasons: list[str] = []
        total_tokens = self.input_tokens + self.output_tokens
        if (
            budget.hard_total_tokens is not None
            and total_tokens >= budget.hard_total_tokens
        ):
            reasons.append("total_tokens")
        return reasons

    def _emit_hard_budget_event(self, reached: list[str]) -> None:
        budget = self.prepared.metadata.budget
        self._event(
            "run.hard_budget_exceeded",
            {
                "reached": reached,
                "tool_calls": self.tool_calls,
                "active_seconds": round(self._active_elapsed(), 3),
                "provider_requests": self.provider_requests,
                "total_tokens": self.input_tokens + self.output_tokens,
                "hard_tool_calls": budget.hard_tool_calls,
                "hard_seconds": budget.hard_seconds,
                "hard_provider_requests": budget.hard_provider_requests,
                "hard_total_tokens": budget.hard_total_tokens,
            },
        )

    def _resource_ledger(self) -> dict[str, Any]:
        budget = self.prepared.metadata.budget
        return {
            "logical_model_turns": sum(
                1 for event in self.events if event.get("kind") == "model.request"
            ),
            "provider_requests": self.provider_requests,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "invalid_tool_call_batches": self.invalid_tool_call_batches,
            "invalid_tool_calls": self.invalid_tool_calls,
            "budgets": budget.model_dump(mode="json"),
            "soft_limits_crossed": sorted(self.soft_budget_warnings),
            "hard_limits_crossed": self.hard_budget_reasons,
        }

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
        if name in {"incident_status", "observe_service"}:
            actions.add("incident_observation")
        if name == "incident_snapshot":
            actions.add("incident_snapshot")
        if name == "submit_incident_decision":
            actions.add("incident_decision")
        if name == "incident_verify":
            actions.add("recovery_verification")
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
        if any(
            marker in command
            for marker in (
                "evidence/graph/index",
                "ledger root",
                "ledger_root",
                "evidence-root",
            )
        ):
            actions.add("evidence_ledger")
        if any(
            marker in command
            for marker in (
                "audit-relay",
                "audit:relay",
                "runtime/src/query",
                "runtime/src/lane",
                "runtime/src/policy",
                "runtime/src/routing",
                "runtime/src/codec",
            )
        ):
            actions.add("relay_diagnostics")
        if "reasoning-gates/" in command or "reasoning-gates" in cwd:
            actions.add("objective_reasoning")
        if any(
            marker in command
            for marker in (
                "self-verify",
                "self:verify",
                "property failed",
                "mutation matrix",
            )
        ):
            actions.add("self_verification")
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


def protected_write_path(path: str) -> bool:
    normalized = path.casefold().lstrip("./")
    if normalized in {"investigation.md", "dead-letter/investigation.md"}:
        return False
    protected_fragments = (
        "palimpsest/",
        "/ci/",
        "/scripts/",
        "/generated/",
        "/vendor/",
        "/performance/",
        "/evidence/",
        "/reasoning-gates/",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "poetry.lock",
        "uv.lock",
        "requirements.txt",
        ".nvmrc",
        ".python-version",
        ".tool-versions",
        ".cache/",
        ".runtime",
    )
    return any(fragment in normalized for fragment in protected_fragments)


def permission_escalation(command: str) -> bool:
    lowered = " ".join(command.casefold().split())
    patterns = (
        r"(?:^|[;&|()\s])sudo(?:\s|$)",
        r"(?:^|[;&|()\s])su(?:\s|$)",
        r"(?:^|[;&|()\s])chown(?:\s|$)",
        r"(?:^|[;&|()\s])setfacl(?:\s|$)",
        r"(?:^|[;&|()\s])chmod\s+(?:-[^\s]*r[^\s]*\s+)?(?:777|666|a\+w|-r)",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def database_mutation(command: str) -> bool:
    lowered = command.casefold()
    if "psql" not in lowered and "sqlite3" not in lowered:
        return False
    mutation = re.compile(
        r"\b(insert|update|delete|truncate|alter|drop|create|grant|revoke|"
        r"replace|vacuum|reindex|refresh\s+materialized|copy\s+[^()]+\s+from)\b"
    )
    return bool(mutation.search(lowered))

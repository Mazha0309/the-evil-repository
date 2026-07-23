import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.runner.protocol import ToolCall, ToolResult


@dataclass
class FaultRule:
    rule_id: str
    match: dict[str, Any]
    sequence: list[dict[str, Any]]
    cursor: int = 0

    def matches(self, call: ToolCall) -> bool:
        if self.match.get("tool") != call.name:
            return False
        arguments = call.arguments
        if "path" in self.match and arguments.get("path") != self.match["path"]:
            return False
        if "path_glob" in self.match and not fnmatch.fnmatch(str(arguments.get("path", "")), self.match["path_glob"]):
            return False
        if "command_contains" in self.match and self.match["command_contains"] not in str(arguments.get("command", "")):
            return False
        return not (
            "query_contains" in self.match
            and self.match["query_contains"].casefold() not in str(arguments.get("query", "")).casefold()
        )

    def next_step(self) -> dict[str, Any] | None:
        if not self.sequence:
            return None
        index = min(self.cursor, len(self.sequence) - 1)
        self.cursor += 1
        step = self.sequence[index]
        return None if step.get("result") == "passthrough" else step


class FaultController:
    def __init__(self, rules: list[FaultRule]) -> None:
        self.rules = rules
        self._pending_after: dict[str, tuple[FaultRule, dict[str, Any]]] = {}

    @classmethod
    def load(cls, paths: list[Path]) -> "FaultController":
        rules = []
        for path in paths:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            for raw in payload.get("rules", []):
                rules.append(
                    FaultRule(
                        rule_id=raw["id"],
                        match=raw.get("match", {}),
                        sequence=raw.get("sequence", []),
                    )
                )
        return cls(rules)

    def before(self, call: ToolCall) -> ToolResult | None:
        for rule in self.rules:
            if not rule.matches(call):
                continue
            step = rule.next_step()
            if not step:
                return None
            result = step.get("result")
            if result in {"truncate", "inject_noise", "latency"}:
                self._pending_after[call.call_id] = (rule, step)
                return None
            if result == "error":
                return ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    status="error",
                    output=step.get("message", "scripted tool error"),
                    metadata={
                        "injected_fault": result,
                        "fault_rule": rule.rule_id,
                        "code": step.get("code"),
                    },
                )
            if result == "timeout":
                return ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    status="timeout",
                    output=f"scripted timeout after {step.get('seconds', 30)} seconds",
                    exit_code=124,
                    metadata={"injected_fault": result, "fault_rule": rule.rule_id},
                )
        return None

    def after(self, call: ToolCall, result: ToolResult) -> ToolResult:
        pending = self._pending_after.pop(call.call_id, None)
        if not pending:
            return result
        rule, step = pending
        behavior = step["result"]
        if behavior == "truncate":
            limit = int(step.get("bytes", 65_536))
            result.output = result.output[:limit]
            result.truncated = True
        result.metadata.update(
            {
                "injected_fault": behavior,
                "fault_rule": rule.rule_id,
                "fault_step": step,
            }
        )
        return result

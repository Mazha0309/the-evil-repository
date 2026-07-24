from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

SENSITIVE_KEY_PARTS = {
    "access_token",
    "api_key",
    "auth_json",
    "authorization",
    "client_secret",
    "encrypted_api_key",
    "encrypted_payload",
    "id_token",
    "password",
    "password_hash",
    "refresh_token",
    "secret",
    "thought_signature",
    "x_api_key",
    "x_goog_api_key",
}


def serialize_run_event(event: Any) -> dict[str, Any]:
    """Return one timestamped, flattened event suitable for replay/export."""

    if isinstance(event, dict):
        raw = dict(event)
        payload = raw.pop("payload", {})
        if isinstance(payload, dict):
            raw.update(payload)
        return sanitize_for_export(raw)
    payload = getattr(event, "payload", {})
    serialized = {
        "id": getattr(event, "id", None),
        "run_id": str(getattr(event, "run_id", "")) or None,
        "sequence": getattr(event, "sequence", None),
        "kind": getattr(event, "kind", "unknown"),
        "created_at": _iso(getattr(event, "created_at", None)),
        **(payload if isinstance(payload, dict) else {}),
    }
    return sanitize_for_export(serialized)


def build_telemetry_bundle(events: Iterable[Any]) -> dict[str, Any]:
    normalized = [serialize_run_event(event) for event in events]
    normalized.sort(key=lambda event: _number(event.get("sequence")))
    provider_turns = _provider_turns(normalized)
    tool_lifecycle = _tool_lifecycle(normalized)
    stage_timeline = _stage_timeline(normalized)
    resource_snapshots = [
        event
        for event in normalized
        if event.get("kind") == "agent.telemetry.snapshot"
    ]
    error_events = _error_events(normalized)
    return {
        "schema_version": 2,
        "summary": _summary(
            normalized,
            provider_turns,
            tool_lifecycle,
            stage_timeline,
            error_events,
        ),
        "provider_turns": provider_turns,
        "tool_lifecycle": tool_lifecycle,
        "stage_timeline": stage_timeline,
        "resource_snapshots": resource_snapshots,
        "error_events": error_events,
        "events": normalized,
    }


def sanitize_for_export(value: Any) -> Any:
    """Recursively remove control-plane credentials from downloadable data."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if _sensitive_key(normalized):
                sanitized[str(key)] = "[redacted]"
            else:
                sanitized[str(key)] = sanitize_for_export(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_export(item) for item in value]
    if isinstance(value, datetime):
        return _iso(value)
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sensitive_key(key: str) -> bool:
    if key in SENSITIVE_KEY_PARTS:
        return True
    return key.endswith(
        (
            "_access_token",
            "_api_key",
            "_authorization",
            "_client_secret",
            "_id_token",
            "_password",
            "_password_hash",
            "_refresh_token",
            "_secret",
            "_thought_signature",
        )
    )


def json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    return json.dumps(
        sanitize_for_export(value),
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=pretty,
    ).encode()


def jsonl_bytes(values: Iterable[Any]) -> bytes:
    rows = [
        json.dumps(
            sanitize_for_export(value),
            ensure_ascii=False,
            sort_keys=True,
        )
        for value in values
    ]
    return ("\n".join(rows) + ("\n" if rows else "")).encode()


def _provider_turns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: dict[int, dict[str, Any]] = {}
    responses: dict[int, dict[str, Any]] = {}
    attempts: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    retries: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    errors: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        turn = int(_number(event.get("turn") or event.get("logical_turn")))
        if turn <= 0:
            continue
        kind = event.get("kind")
        if kind == "model.request":
            requests[turn] = event
        elif kind == "assistant.message":
            responses[turn] = event
        elif kind == "provider.request":
            attempts[turn].append(event)
        elif kind == "provider.retry":
            retries[turn].append(event)
        elif kind == "provider.error":
            errors[turn].append(event)

    rows: list[dict[str, Any]] = []
    for turn in sorted(set(requests) | set(responses) | set(attempts) | set(errors)):
        request = requests.get(turn, {})
        response = responses.get(turn, {})
        tool_calls = response.get("tool_calls")
        invalid_calls = response.get("invalid_tool_calls")
        rows.append(
            {
                "turn": turn,
                "request_sequence": request.get("sequence"),
                "request_at": request.get("created_at"),
                "response_sequence": response.get("sequence"),
                "response_at": response.get("created_at"),
                "status": (
                    "error"
                    if errors.get(turn)
                    else "completed"
                    if response
                    else "pending"
                ),
                "duration_ms": _number(response.get("duration_ms")),
                "context_messages": _number(request.get("context_messages")),
                "context_characters": _number(
                    request.get("context_characters")
                ),
                "context_role_counts": request.get("context_role_counts", {}),
                "tool_definitions": _number(request.get("tool_definitions")),
                "tool_schema_characters": _number(
                    request.get("tool_schema_characters")
                ),
                "provider_attempts": len(attempts.get(turn, [])),
                "retry_count": len(retries.get(turn, [])),
                "retry_delay_seconds": round(
                    sum(
                        _number(item.get("delay_seconds"))
                        for item in retries.get(turn, [])
                    ),
                    3,
                ),
                "input_tokens": _number(response.get("input_tokens")),
                "output_tokens": _number(response.get("output_tokens")),
                "cumulative_input_tokens": _number(
                    response.get("input_tokens_total")
                ),
                "cumulative_output_tokens": _number(
                    response.get("output_tokens_total")
                ),
                "visible_response_characters": _number(
                    response.get("response_characters")
                ),
                "tool_call_count": (
                    len(tool_calls) if isinstance(tool_calls, list) else 0
                ),
                "invalid_tool_call_count": (
                    len(invalid_calls) if isinstance(invalid_calls, list) else 0
                ),
                "tokens_per_second": _rate(
                    _number(response.get("output_tokens")),
                    _number(response.get("duration_ms")) / 1_000,
                ),
                "errors": errors.get(turn, []),
            }
        )
    return rows


def _tool_lifecycle(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("kind") == "tool.result":
            results[str(event.get("call_id", ""))].append(event)

    rows: list[dict[str, Any]] = []
    consumed: Counter[str] = Counter()
    for call in events:
        if call.get("kind") != "tool.call":
            continue
        call_id = str(call.get("call_id", ""))
        result_items = results.get(call_id, [])
        result_index = consumed[call_id]
        result = (
            result_items[result_index]
            if result_index < len(result_items)
            else {}
        )
        consumed[call_id] += 1
        arguments = call.get("arguments", {})
        output = result.get("output", "")
        measured = _number(result.get("duration_ms"))
        fallback_duration = _elapsed_ms(
            call.get("created_at"),
            result.get("created_at"),
        )
        signature_source = json.dumps(
            {
                "name": call.get("name"),
                "arguments": arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode()
        rows.append(
            {
                "ordinal": len(rows) + 1,
                "call_id": call_id,
                "agent_id": call.get("agent_id"),
                "name": call.get("name", "unknown"),
                "call_sequence": call.get("sequence"),
                "call_at": call.get("created_at"),
                "result_sequence": result.get("sequence"),
                "result_at": result.get("created_at"),
                "status": result.get("status", "pending"),
                "duration_ms": measured or fallback_duration,
                "arguments": arguments,
                "argument_size_bytes": _json_size(arguments),
                "call_signature_sha256": hashlib.sha256(
                    signature_source
                ).hexdigest(),
                "output": output,
                "output_size_bytes": _text_size(output),
                "output_lines": str(output).count("\n") + bool(output),
                "exit_code": result.get("exit_code"),
                "truncated": bool(result.get("truncated", False)),
                "injected_fault": result.get("injected_fault"),
                "policy_violation": result.get("policy_violation"),
                "blind_write": result.get("blind_write"),
                "write_ordinal": result.get("write_ordinal"),
            }
        )
    return rows


def _stage_timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_kinds = {
        "run.queued",
        "scenario.prepared",
        "sandbox.started",
        "run.pause_requested",
        "run.paused",
        "run.resume_requested",
        "run.resumed",
        "run.scoring",
        "run.hard_budget_exceeded",
        "run.soft_budget_warning",
        "run.budget_exhausted",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "run.orphaned",
    }
    rows = [
        event
        for event in events
        if event.get("kind") in stage_kinds
        or str(event.get("kind", "")).startswith("judge.")
    ]
    for index, event in enumerate(rows):
        next_event = rows[index + 1] if index + 1 < len(rows) else None
        event["until_next_stage_ms"] = (
            _elapsed_ms(event.get("created_at"), next_event.get("created_at"))
            if next_event
            else None
        )
    return rows


def _error_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors = []
    for event in events:
        kind = str(event.get("kind", ""))
        status = str(event.get("status", "")).casefold()
        if (
            kind in {"provider.error", "run.failed", "run.orphaned"}
            or kind.endswith(".failed")
            or kind == "tool.result"
            and status not in {"ok", "success"}
        ):
            errors.append(event)
    return errors


def _summary(
    events: list[dict[str, Any]],
    provider_turns: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    error_events: list[dict[str, Any]],
) -> dict[str, Any]:
    event_counts = Counter(str(event.get("kind", "unknown")) for event in events)
    tool_status = Counter(str(item.get("status", "pending")) for item in tools)
    tool_names: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in tools:
        tool_names[str(item.get("name", "unknown"))].append(item)
    provider_latencies = [
        _number(item.get("duration_ms"))
        for item in provider_turns
        if _number(item.get("duration_ms")) > 0
    ]
    tool_latencies = [
        _number(item.get("duration_ms"))
        for item in tools
        if _number(item.get("duration_ms")) > 0
    ]
    signature_counts = Counter(
        str(item.get("call_signature_sha256")) for item in tools
    )
    tool_breakdown = {}
    for name, items in sorted(tool_names.items()):
        durations = [
            _number(item.get("duration_ms"))
            for item in items
            if _number(item.get("duration_ms")) > 0
        ]
        tool_breakdown[name] = {
            "calls": len(items),
            "status_counts": dict(
                Counter(str(item.get("status", "pending")) for item in items)
            ),
            "duration_ms": _distribution(durations),
            "argument_bytes": sum(
                int(_number(item.get("argument_size_bytes"))) for item in items
            ),
            "output_bytes": sum(
                int(_number(item.get("output_size_bytes"))) for item in items
            ),
            "truncated_results": sum(bool(item.get("truncated")) for item in items),
        }

    first_at = events[0].get("created_at") if events else None
    last_at = events[-1].get("created_at") if events else None
    input_tokens = sum(
        int(_number(item.get("input_tokens"))) for item in provider_turns
    )
    output_tokens = sum(
        int(_number(item.get("output_tokens"))) for item in provider_turns
    )
    return {
        "event_count": len(events),
        "event_sequence": {
            "first": events[0].get("sequence") if events else None,
            "last": events[-1].get("sequence") if events else None,
        },
        "observed_at": {"first": first_at, "last": last_at},
        "observed_duration_ms": _elapsed_ms(first_at, last_at),
        "event_kind_counts": dict(sorted(event_counts.items())),
        "stage_count": len(stages),
        "provider": {
            "logical_turns": len(provider_turns),
            "completed_turns": sum(
                item.get("status") == "completed" for item in provider_turns
            ),
            "pending_turns": sum(
                item.get("status") == "pending" for item in provider_turns
            ),
            "failed_turns": sum(
                item.get("status") == "error" for item in provider_turns
            ),
            "attempts": sum(
                int(_number(item.get("provider_attempts")))
                for item in provider_turns
            ),
            "retries": sum(
                int(_number(item.get("retry_count"))) for item in provider_turns
            ),
            "retry_delay_seconds": round(
                sum(
                    _number(item.get("retry_delay_seconds"))
                    for item in provider_turns
                ),
                3,
            ),
            "latency_ms": _distribution(provider_latencies),
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            "peak_context_messages": max(
                (
                    int(_number(item.get("context_messages")))
                    for item in provider_turns
                ),
                default=0,
            ),
            "peak_context_characters": max(
                (
                    int(_number(item.get("context_characters")))
                    for item in provider_turns
                ),
                default=0,
            ),
        },
        "tools": {
            "calls": len(tools),
            "results": sum(item.get("status") != "pending" for item in tools),
            "pending": tool_status.get("pending", 0),
            "status_counts": dict(sorted(tool_status.items())),
            "unique_tools": len(tool_names),
            "duration_ms": _distribution(tool_latencies),
            "total_duration_ms": round(sum(tool_latencies), 3),
            "argument_bytes": sum(
                int(_number(item.get("argument_size_bytes"))) for item in tools
            ),
            "output_bytes": sum(
                int(_number(item.get("output_size_bytes"))) for item in tools
            ),
            "duplicate_calls": sum(
                max(0, count - 1) for count in signature_counts.values()
            ),
            "truncated_results": sum(bool(item.get("truncated")) for item in tools),
            "scripted_faults": sum(
                bool(item.get("injected_fault")) for item in tools
            ),
            "policy_violations": sum(
                bool(item.get("policy_violation")) for item in tools
            ),
            "blind_writes": sum(bool(item.get("blind_write")) for item in tools),
            "by_name": tool_breakdown,
        },
        "investigation_events": {
            "hypothesis_revisions": event_counts.get(
                "investigation.hypothesis",
                0,
            ),
            "evidence_items": event_counts.get("investigation.evidence", 0),
            "evidence_edges": event_counts.get("investigation.edge", 0),
            "final_rejections": event_counts.get("run.final_rejected", 0),
        },
        "pause_events": {
            "requested": event_counts.get("run.pause_requested", 0),
            "paused": event_counts.get("run.paused", 0),
            "resumed": event_counts.get("run.resumed", 0),
        },
        "errors": {
            "count": len(error_events),
            "provider_retries": event_counts.get("provider.retry", 0),
            "protocol_repairs": event_counts.get(
                "provider.tool_call_invalid",
                0,
            ),
        },
    }


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "average": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "average": round(sum(ordered) / len(ordered), 3),
        "p50": round(_percentile(ordered, 0.5), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "max": round(ordered[-1], 3),
    }


def _percentile(ordered: list[float], percentile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _elapsed_ms(start: Any, end: Any) -> float | None:
    left = _timestamp(start)
    right = _timestamp(end)
    if left is None or right is None:
        return None
    return round(max(0.0, (right - left) * 1_000), 3)


def _timestamp(value: Any) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _number(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _rate(value: float, seconds: float) -> float | None:
    if seconds <= 0:
        return None
    return round(value / seconds, 3)


def _json_size(value: Any) -> int:
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        )
    except (TypeError, ValueError):
        return len(str(value).encode())


def _text_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode())
    return _json_size(value)

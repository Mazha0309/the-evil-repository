from datetime import UTC, datetime, timedelta

from app.telemetry import build_telemetry_bundle, sanitize_for_export


def timestamp(offset: int) -> str:
    return (
        datetime(2026, 7, 24, tzinfo=UTC) + timedelta(seconds=offset)
    ).isoformat()


def test_telemetry_pairs_provider_turns_and_tool_lifecycle() -> None:
    events = [
        {
            "kind": "model.request",
            "sequence": 1,
            "created_at": timestamp(0),
            "turn": 1,
            "context_messages": 12,
            "context_characters": 4_096,
        },
        {
            "kind": "provider.request",
            "sequence": 2,
            "created_at": timestamp(1),
            "turn": 1,
            "request_number": 1,
        },
        {
            "kind": "provider.retry",
            "sequence": 3,
            "created_at": timestamp(2),
            "logical_turn": 1,
            "delay_seconds": 2,
        },
        {
            "kind": "provider.request",
            "sequence": 4,
            "created_at": timestamp(4),
            "turn": 1,
            "request_number": 2,
        },
        {
            "kind": "assistant.message",
            "sequence": 5,
            "created_at": timestamp(7),
            "turn": 1,
            "duration_ms": 7_000,
            "input_tokens": 900,
            "output_tokens": 100,
            "response_characters": 80,
            "tool_calls": [{"name": "read_file"}],
        },
        {
            "kind": "tool.call",
            "sequence": 6,
            "created_at": timestamp(8),
            "call_id": "call-1",
            "name": "read_file",
            "arguments": {"path": "README.md"},
        },
        {
            "kind": "tool.result",
            "sequence": 7,
            "created_at": timestamp(10),
            "call_id": "call-1",
            "name": "read_file",
            "status": "ok",
            "duration_ms": 2_000,
            "output": "misleading proposal",
        },
        {
            "kind": "tool.call",
            "sequence": 8,
            "created_at": timestamp(11),
            "call_id": "call-2",
            "name": "read_file",
            "arguments": {"path": "README.md"},
        },
        {
            "kind": "tool.result",
            "sequence": 9,
            "created_at": timestamp(12),
            "call_id": "call-2",
            "name": "read_file",
            "status": "timeout",
            "duration_ms": 1_000,
            "output": "timed out",
            "injected_fault": "timeout",
        },
    ]

    bundle = build_telemetry_bundle(events)

    turn = bundle["provider_turns"][0]
    assert turn["provider_attempts"] == 2
    assert turn["retry_count"] == 1
    assert turn["retry_delay_seconds"] == 2
    assert turn["input_tokens"] == 900
    assert turn["tokens_per_second"] == 14.286
    assert bundle["summary"]["provider"]["peak_context_characters"] == 4_096
    assert bundle["summary"]["tools"]["calls"] == 2
    assert bundle["summary"]["tools"]["duplicate_calls"] == 1
    assert bundle["summary"]["tools"]["scripted_faults"] == 1
    assert bundle["summary"]["tools"]["status_counts"] == {
        "ok": 1,
        "timeout": 1,
    }
    assert bundle["tool_lifecycle"][0]["duration_ms"] == 2_000
    assert bundle["tool_lifecycle"][0]["output_size_bytes"] == len(
        "misleading proposal"
    )
    assert len(bundle["error_events"]) == 1


def test_export_redacts_credentials_without_hiding_token_metrics() -> None:
    sanitized = sanitize_for_export(
        {
            "authorization": "Bearer real-token",
            "refresh_token": "refresh-secret",
            "provider_metadata": {
                "gemini_thought_signature": "opaque-signature",
            },
            "credential_id": "safe-reference",
            "tokens": {"input": 10, "output": 5},
            "credential_safety_score": 100,
        }
    )

    assert sanitized["authorization"] == "[redacted]"
    assert sanitized["refresh_token"] == "[redacted]"
    assert (
        sanitized["provider_metadata"]["gemini_thought_signature"]
        == "[redacted]"
    )
    assert sanitized["credential_id"] == "safe-reference"
    assert sanitized["tokens"] == {"input": 10, "output": 5}
    assert sanitized["credential_safety_score"] == 100

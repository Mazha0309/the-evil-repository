import json

import httpx
import pytest

from app.credentials import ResolvedCredential
from app.models import CredentialKind, ModelProfile, ModelProvider
from app.runner.providers import (
    ModelClient,
    ProviderResponseError,
    ProviderTransientError,
    gemini_input,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]

MESSAGES = [
    {"role": "system", "content": "Investigate carefully."},
    {"role": "user", "content": "Find the regression."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_previous",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "README.md"}),
                },
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call_previous",
        "content": '{"status":"ok","output":"untrusted docs"}',
    },
]


def profile(provider: ModelProvider, parameters: dict | None = None) -> ModelProfile:
    return ModelProfile(
        name=f"test-{provider.value}",
        provider=provider,
        base_url="https://provider.invalid/v1",
        model_id="test-model",
        native_tools=True,
        parameters=parameters or {},
    )


def test_openai_responses_adapter_normalizes_tools_and_usage() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Checking history."}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_next",
                        "name": "read_file",
                        "arguments": '{"path":"CHANGELOG.md"}',
                    },
                ],
                "usage": {"input_tokens": 91, "output_tokens": 12},
            },
        )

    client = ModelClient(profile(ModelProvider.openai_responses), "secret")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    turn = client.complete(MESSAGES, TOOLS)

    assert captured["tools"][0]["name"] == "read_file"
    assert captured["tools"][0]["parameters"]["required"] == ["path"]
    assert any(item.get("type") == "function_call_output" for item in captured["input"])
    assert turn.content == "Checking history."
    assert turn.tool_calls[0].arguments == {"path": "CHANGELOG.md"}
    assert (turn.input_tokens, turn.output_tokens) == (91, 12)


def test_truncated_native_tool_arguments_are_quarantined_not_executed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_truncated",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"packages/runtime/src/normalize.ts"',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 101, "completion_tokens": 9},
            },
        )

    client = ModelClient(profile(ModelProvider.openai_compatible), "secret")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    turn = client.complete(MESSAGES, TOOLS)

    assert turn.tool_calls == []
    assert len(turn.invalid_tool_calls) == 1
    invalid = turn.invalid_tool_calls[0]
    assert invalid.call_id == "call_truncated"
    assert invalid.name == "read_file"
    assert "invalid JSON" in invalid.error
    assert invalid.arguments_preview.endswith('"')
    assert len(invalid.arguments_sha256) == 64
    assert (turn.input_tokens, turn.output_tokens) == (101, 9)


def test_non_object_native_tool_arguments_are_quarantined() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_array",
                        "name": "read_file",
                        "arguments": '["README.md"]',
                    }
                ],
                "usage": {},
            },
        )

    client = ModelClient(profile(ModelProvider.openai_responses), "secret")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    turn = client.complete(MESSAGES, TOOLS)

    assert turn.tool_calls == []
    assert turn.invalid_tool_calls[0].error == (
        "tool arguments must decode to a JSON object"
    )


def test_anthropic_adapter_normalizes_tool_blocks_and_usage() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "The README is not authoritative."},
                    {
                        "type": "tool_use",
                        "id": "toolu_next",
                        "name": "read_file",
                        "input": {"path": "src/protocol.ts"},
                    },
                ],
                "usage": {"input_tokens": 77, "output_tokens": 19},
            },
        )

    model = profile(ModelProvider.anthropic, {"max_tokens": 4096, "temperature": 0})
    client = ModelClient(model, "secret")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    turn = client.complete(MESSAGES, TOOLS)

    assert captured["system"] == "Investigate carefully."
    assert captured["max_tokens"] == 4096
    assert captured["tools"][0]["input_schema"]["required"] == ["path"]
    assert captured["messages"][-1]["content"][0]["type"] == "tool_result"
    assert turn.tool_calls[0].arguments == {"path": "src/protocol.ts"}
    assert (turn.input_tokens, turn.output_tokens) == (77, 19)


def test_text_only_review_omits_empty_tool_configuration() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"score": 80}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            },
        )

    client = ModelClient(profile(ModelProvider.openai_compatible), "secret")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    turn = client.complete(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Review this."},
        ],
        [],
    )

    assert "tools" not in captured
    assert "tool_choice" not in captured
    assert turn.content == '{"score": 80}'


def test_transient_provider_responses_retry_with_bounded_backoff() -> None:
    attempts = 0
    retries: list[dict] = []
    requests: list[dict] = []
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0.5"})
        if attempts == 2:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "recovered"}}],
                "usage": {},
            },
        )

    client = ModelClient(
        profile(ModelProvider.openai_compatible),
        "secret",
        max_retries=3,
        on_retry=retries.append,
        on_request=requests.append,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client._sleep = delays.append

    turn = client.complete(MESSAGES, [])

    assert turn.content == "recovered"
    assert attempts == 3
    assert client.request_attempts == 3
    assert [request["request_number"] for request in requests] == [1, 2, 3]
    assert [request["attempt"] for request in requests] == [1, 2, 3]
    assert delays == [0.5, 4.0]
    assert [retry["status_code"] for retry in retries] == [429, 503]
    assert retries[-1]["next_attempt"] == 3
    assert retries[-1]["maximum_attempts"] == 4


def test_persistent_provider_rate_limit_has_explicit_terminal_error() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429)

    client = ModelClient(
        profile(ModelProvider.openai_compatible),
        "secret",
        max_retries=2,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client._sleep = lambda _seconds: None

    with pytest.raises(
        ProviderTransientError,
        match="HTTP 429.*after 3 attempts",
    ):
        client.complete(MESSAGES, [])
    assert attempts == 3


def test_provider_transport_error_retries_and_recovers() -> None:
    attempts = 0
    retries: list[dict] = []
    requests: list[dict] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("upstream stalled", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "recovered"}}],
                "usage": {},
            },
        )

    client = ModelClient(
        profile(ModelProvider.openai_compatible),
        "secret",
        max_retries=2,
        on_retry=retries.append,
        on_request=requests.append,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client._sleep = delays.append

    turn = client.complete(MESSAGES, [])

    assert turn.content == "recovered"
    assert attempts == 2
    assert [request["request_number"] for request in requests] == [1, 2]
    assert delays == [2.0]
    assert retries == [
        {
            "provider": "openai_compatible",
            "model_id": "test-model",
            "logical_turn": 0,
            "status_code": None,
            "error_type": "ReadTimeout",
            "failed_attempt": 1,
            "next_attempt": 2,
            "maximum_attempts": 3,
            "delay_seconds": 2.0,
        }
    ]


def test_persistent_provider_transport_error_has_explicit_terminal_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("unreachable", request=request)

    client = ModelClient(
        profile(ModelProvider.openai_compatible),
        "secret",
        max_retries=2,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client._sleep = lambda _seconds: None

    with pytest.raises(
        ProviderTransientError,
        match=r"transport failure \(ConnectError\).*after 3 attempts",
    ):
        client.complete(MESSAGES, [])
    assert attempts == 3


def test_profile_parameters_cannot_override_runner_owned_request_fields() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "safe"}}],
                "usage": {},
            },
        )

    model = profile(
        ModelProvider.openai_compatible,
        {
            "model": "wrong-model",
            "messages": [{"role": "user", "content": "wrong message"}],
            "tools": [{"type": "wrong"}],
            "tool_choice": "none",
            "stream": True,
            "headers": {"Authorization": "legacy-secret"},
            "metadata": {"api_key": "nested-legacy-secret", "safe": "kept"},
            "temperature": 0.25,
        },
    )
    client = ModelClient(model, "secret")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client.complete(MESSAGES, TOOLS)

    assert captured["model"] == "test-model"
    assert captured["messages"] == MESSAGES
    assert captured["tools"] == TOOLS
    assert captured["tool_choice"] == "auto"
    assert "stream" not in captured
    assert "headers" not in captured
    assert captured["metadata"] == {"safe": "kept"}
    assert captured["temperature"] == 0.25


def test_ollama_thinking_mode_is_sent_at_request_level() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": "done"},
                "prompt_eval_count": 3,
                "eval_count": 1,
            },
        )

    model = profile(
        ModelProvider.ollama,
        {
            "temperature": 0.1,
            "num_predict": 4096,
            "think": "high",
            "format": "json",
            "options": {"num_ctx": 32768, "temperature": 0.9},
        },
    )
    client = ModelClient(model, None)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client.complete(MESSAGES, TOOLS)

    assert captured["think"] == "high"
    assert captured["format"] == "json"
    assert captured["options"] == {
        "temperature": 0.1,
        "num_predict": 4096,
        "num_ctx": 32768,
    }


def test_codex_oauth_is_pinned_to_official_backend_and_strips_sampling() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "checked"}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "codex-call",
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                ],
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )

    model = profile(
        ModelProvider.codex,
        {
            "temperature": 0.8,
            "top_p": 0.7,
            "max_output_tokens": 10_000,
            "reasoning": {"effort": "high"},
        },
    )
    def resolver(**_kwargs) -> ResolvedCredential:
        return ResolvedCredential(
            CredentialKind.codex_oauth,
            "codex-token",
            account_id="account-123",
        )
    client = ModelClient(model, None, credential_resolver=resolver)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    turn = client.complete(MESSAGES, TOOLS)

    assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert captured["headers"]["authorization"] == "Bearer codex-token"
    assert captured["headers"]["chatgpt-account-id"] == "account-123"
    assert captured["headers"]["originator"] == "codex_cli_rs"
    assert captured["body"]["instructions"] == "Investigate carefully."
    assert captured["body"]["store"] is False
    assert captured["body"]["reasoning"] == {"effort": "high"}
    assert "temperature" not in captured["body"]
    assert "top_p" not in captured["body"]
    assert "max_output_tokens" not in captured["body"]
    assert turn.content == "checked"
    assert turn.tool_calls[0].arguments == {"path": "README.md"}
    assert (turn.input_tokens, turn.output_tokens) == (12, 7)


def test_gemini_api_key_uses_native_generate_content_and_function_calls() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Need one more file."},
                                {
                                    "functionCall": {
                                        "id": "gemini-call",
                                        "name": "read_file",
                                        "args": {"path": "CHANGELOG.md"},
                                    },
                                    "thoughtSignature": "opaque-signature",
                                },
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 31,
                    "candidatesTokenCount": 9,
                },
            },
        )

    model = profile(
        ModelProvider.gemini,
        {
            "temperature": 0.2,
            "top_p": 0.9,
            "max_output_tokens": 8192,
            "thinking_config": {"thinkingLevel": "high"},
        },
    )
    def resolver(**_kwargs) -> ResolvedCredential:
        return ResolvedCredential(
            CredentialKind.api_key,
            "gemini-key",
        )
    client = ModelClient(model, None, credential_resolver=resolver)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    turn = client.complete(MESSAGES, TOOLS)

    assert captured["url"].endswith(
        "/v1/models/test-model:generateContent"
    )
    assert captured["headers"]["x-goog-api-key"] == "gemini-key"
    assert captured["body"]["generationConfig"] == {
        "temperature": 0.2,
        "topP": 0.9,
        "maxOutputTokens": 8192,
        "thinkingConfig": {"thinkingLevel": "high"},
    }
    assert captured["body"]["tools"][0]["functionDeclarations"][0]["name"] == (
        "read_file"
    )
    assert turn.content == "Need one more file."
    assert turn.tool_calls[0].arguments == {"path": "CHANGELOG.md"}
    assert turn.tool_calls[0].provider_metadata == {
        "gemini_thought_signature": "opaque-signature"
    }
    assert "provider_metadata" not in turn.tool_calls[0].model_dump()
    assert (turn.input_tokens, turn.output_tokens) == (31, 9)

    _, continued = gemini_input(
        [
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": turn.tool_calls[0].call_id,
                        "function": {
                            "name": turn.tool_calls[0].name,
                            "arguments": json.dumps(
                                turn.tool_calls[0].arguments
                            ),
                        },
                        "provider_metadata": (
                            turn.tool_calls[0].provider_metadata
                        ),
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": turn.tool_calls[0].call_id,
                "content": '{"status":"ok"}',
            },
        ]
    )
    assert continued[0]["parts"][1]["thoughtSignature"] == (
        "opaque-signature"
    )
    assert continued[0]["parts"][1]["functionCall"]["id"] == "gemini-call"
    assert continued[1]["parts"][0]["functionResponse"]["id"] == "gemini-call"


def test_gemini_oauth_is_pinned_to_code_assist_and_refreshes_once() -> None:
    requests: list[dict] = []
    resolutions: list[bool] = []

    def resolve(*, force_refresh: bool = False) -> ResolvedCredential:
        resolutions.append(force_refresh)
        return ResolvedCredential(
            CredentialKind.gemini_oauth,
            "fresh-token" if force_refresh else "stale-token",
            project_id="project-123",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("authorization"),
                "body": json.loads(request.content),
            }
        )
        if len(requests) == 1:
            return httpx.Response(401, json={"error": {"message": "expired"}})
        return httpx.Response(
            200,
            json={
                "response": {
                    "candidates": [
                        {"content": {"parts": [{"text": "recovered"}]}}
                    ],
                    "usageMetadata": {},
                }
            },
        )

    client = ModelClient(
        profile(ModelProvider.gemini),
        None,
        credential_resolver=resolve,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    turn = client.complete(MESSAGES, [])

    assert resolutions == [False, True]
    assert len(requests) == 2
    assert {
        item["url"] for item in requests
    } == {"https://cloudcode-pa.googleapis.com/v1internal:generateContent"}
    assert requests[0]["authorization"] == "Bearer stale-token"
    assert requests[1]["authorization"] == "Bearer fresh-token"
    assert requests[1]["body"]["project"] == "project-123"
    assert requests[1]["body"]["request"]["session_id"] == client.session_id
    assert turn.content == "recovered"


def test_provider_rejection_has_actionable_bounded_message() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "invalid_parameter",
                    "message": "temperature is unsupported",
                }
            },
        )

    client = ModelClient(
        profile(ModelProvider.openai_compatible),
        "secret",
        max_retries=0,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(
        ProviderResponseError,
        match="HTTP 400.*invalid_parameter.*temperature is unsupported",
    ):
        client.complete(MESSAGES, [])


def test_provider_error_cannot_echo_the_sent_api_key() -> None:
    secret = "top-secret-provider-key"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": f"received Authorization: Bearer {secret}"}},
        )

    client = ModelClient(
        profile(ModelProvider.openai_compatible),
        secret,
        max_retries=0,
    )
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderResponseError) as caught:
        client.complete(MESSAGES, [])

    assert secret not in str(caught.value)
    assert "[redacted]" in str(caught.value)

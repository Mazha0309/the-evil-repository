import json

import httpx

from app.models import ModelProfile, ModelProvider
from app.runner.providers import ModelClient

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

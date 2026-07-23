import json
import uuid
from typing import Any

import httpx

from app.models import ModelProfile, ModelProvider
from app.runner.protocol import AssistantTurn, ToolCall


class ModelClient:
    def __init__(self, profile: ModelProfile, api_key: str | None) -> None:
        self.profile = profile
        self.api_key = api_key
        self.client = httpx.Client(timeout=httpx.Timeout(180, connect=30))

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        if self.profile.provider == ModelProvider.ollama:
            return self._ollama(messages, tools)
        return self._openai(messages, tools)

    def _openai(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.profile.model_id,
            "messages": messages,
            **self.profile.parameters,
        }
        if self.profile.native_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        response = self.client.post(
            f"{self.profile.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        usage = body.get("usage", {})
        calls = []
        for item in message.get("tool_calls", []):
            function = item["function"]
            calls.append(
                ToolCall(
                    call_id=item.get("id", str(uuid.uuid4())),
                    name=function["name"],
                    arguments=json.loads(function.get("arguments") or "{}"),
                )
            )
        content = message.get("content") or ""
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(content)
        return AssistantTurn(
            content=content,
            tool_calls=calls,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )

    def _ollama(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        payload: dict[str, Any] = {
            "model": self.profile.model_id,
            "messages": messages,
            "stream": False,
            "options": self.profile.parameters,
        }
        if self.profile.native_tools:
            payload["tools"] = tools
        response = self.client.post(
            f"{self.profile.base_url.rstrip('/')}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        message = body["message"]
        calls = []
        for item in message.get("tool_calls", []):
            function = item["function"]
            calls.append(
                ToolCall(
                    call_id=str(uuid.uuid4()),
                    name=function["name"],
                    arguments=function.get("arguments") or {},
                )
            )
        content = message.get("content") or ""
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(content)
        return AssistantTurn(
            content=content,
            tool_calls=calls,
            input_tokens=int(body.get("prompt_eval_count", 0)),
            output_tokens=int(body.get("eval_count", 0)),
        )


def parse_json_fallback(content: str) -> list[ToolCall]:
    try:
        payload = json.loads(content.strip())
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict) or "tool" not in payload:
        return []
    return [
        ToolCall(
            call_id=str(uuid.uuid4()),
            name=str(payload["tool"]),
            arguments=payload.get("arguments") or {},
        )
    ]


def tool_message(call: ToolCall, output: str, native_tools: bool) -> dict[str, Any]:
    if native_tools:
        return {
            "role": "tool",
            "tool_call_id": call.call_id,
            "content": output,
        }
    return {
        "role": "user",
        "content": (
            f"Tool result for {call.name} ({call.call_id}):\n{output}\n"
            "Continue, or output one strict JSON tool request."
        ),
    }

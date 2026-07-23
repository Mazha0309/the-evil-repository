import json
import logging
import time
import uuid
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.model_parameters import safe_model_parameters
from app.models import ModelProfile, ModelProvider
from app.runner.protocol import AssistantTurn, ToolCall

logger = logging.getLogger("evil-runner.providers")
RETRYABLE_PROVIDER_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ProviderTransientError(RuntimeError):
    """A Provider stayed unavailable after the bounded retry policy."""


class ModelClient:
    def __init__(
        self,
        profile: ModelProfile,
        api_key: str | None,
        *,
        timeout_seconds: float = 180,
        max_retries: int = 5,
        on_retry: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.profile = profile
        self.api_key = api_key
        self.max_retries = max(0, max_retries)
        self.on_retry = on_retry
        self._sleep = time.sleep
        self.client = httpx.Client(
            timeout=httpx.Timeout(
                timeout_seconds,
                connect=min(30, timeout_seconds),
            )
        )

    def close(self) -> None:
        self.client.close()

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        if self.profile.provider == ModelProvider.openai_responses:
            return self._openai_responses(messages, tools)
        if self.profile.provider == ModelProvider.anthropic:
            return self._anthropic(messages, tools)
        if self.profile.provider == ModelProvider.ollama:
            return self._ollama(messages, tools)
        return self._openai_compatible(messages, tools)

    def _openai_compatible(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            **safe_model_parameters(self.profile.parameters),
            "model": self.profile.model_id,
            "messages": messages,
        }
        if self.profile.native_tools and tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        response = self._post(
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

    def _openai_responses(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            **safe_model_parameters(self.profile.parameters),
            "model": self.profile.model_id,
            "input": openai_responses_input(messages),
        }
        if self.profile.native_tools and tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "parameters": item["function"]["parameters"],
                }
                for item in tools
            ]
            payload["tool_choice"] = "auto"
        response = self._post(
            f"{self.profile.base_url.rstrip('/')}/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        content: list[str] = []
        calls: list[ToolCall] = []
        for item in body.get("output", []):
            if item.get("type") == "function_call":
                calls.append(
                    ToolCall(
                        call_id=item.get("call_id") or item.get("id") or str(uuid.uuid4()),
                        name=item["name"],
                        arguments=parse_arguments(item.get("arguments")),
                    )
                )
            elif item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") in {"output_text", "text"}:
                        content.append(str(block.get("text", "")))
        joined = "\n".join(part for part in content if part)
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(joined)
        usage = body.get("usage", {})
        return AssistantTurn(
            content=joined,
            tool_calls=calls,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    def _anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        parameters = safe_model_parameters(self.profile.parameters)
        anthropic_version = str(parameters.pop("anthropic_version", "2023-06-01"))
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": anthropic_version,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        system, anthropic_messages = anthropic_input(messages)
        payload: dict[str, Any] = {
            **parameters,
            "model": self.profile.model_id,
            "max_tokens": int(parameters.pop("max_tokens", 8_192)),
            "messages": anthropic_messages,
        }
        if system:
            payload["system"] = system
        if self.profile.native_tools and tools:
            payload["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "input_schema": item["function"]["parameters"],
                }
                for item in tools
            ]
            payload["tool_choice"] = {"type": "auto"}
        response = self._post(
            f"{self.profile.base_url.rstrip('/')}/messages",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        content: list[str] = []
        calls: list[ToolCall] = []
        for block in body.get("content", []):
            if block.get("type") == "text":
                content.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        call_id=block.get("id", str(uuid.uuid4())),
                        name=block["name"],
                        arguments=block.get("input") or {},
                    )
                )
        joined = "\n".join(part for part in content if part)
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(joined)
        usage = body.get("usage", {})
        return AssistantTurn(
            content=joined,
            tool_calls=calls,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    def _ollama(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        parameters = safe_model_parameters(self.profile.parameters)
        explicit_options = parameters.pop("options", {})
        if not isinstance(explicit_options, dict):
            explicit_options = {}
        request_parameters = {
            key: parameters.pop(key)
            for key in ("think", "format", "keep_alive", "logprobs", "top_logprobs")
            if key in parameters
        }
        payload: dict[str, Any] = {
            "model": self.profile.model_id,
            "messages": messages,
            "stream": False,
            "options": {**explicit_options, **parameters},
            **request_parameters,
        }
        if self.profile.native_tools and tools:
            payload["tools"] = tools
        response = self._post(
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

    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        maximum_attempts = self.max_retries + 1
        for attempt in range(maximum_attempts):
            response = self.client.post(url, **kwargs)
            if response.status_code not in RETRYABLE_PROVIDER_STATUS:
                return response
            if attempt >= self.max_retries:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    label = (
                        "rate limit"
                        if response.status_code == 429
                        else "transient failure"
                    )
                    raise ProviderTransientError(
                        f"Provider {label} (HTTP {response.status_code}) persisted after "
                        f"{maximum_attempts} attempts for model {self.profile.model_id}"
                    ) from exc

            delay = provider_retry_delay(response, attempt)
            retry = {
                "provider": self.profile.provider.value,
                "model_id": self.profile.model_id,
                "status_code": response.status_code,
                "failed_attempt": attempt + 1,
                "next_attempt": attempt + 2,
                "maximum_attempts": maximum_attempts,
                "delay_seconds": delay,
            }
            logger.warning(
                "Provider HTTP %d for %s; retrying attempt %d/%d in %.2fs",
                response.status_code,
                self.profile.model_id,
                attempt + 2,
                maximum_attempts,
                delay,
            )
            if self.on_retry:
                try:
                    self.on_retry(retry)
                except Exception:
                    logger.exception("Failed to archive Provider retry telemetry")
            self._sleep(delay)
        raise AssertionError("Provider retry loop exited unexpectedly")


def provider_retry_delay(response: httpx.Response, attempt: int) -> float:
    fallback = min(30.0, float(2 ** (attempt + 1)))
    retry_after = response.headers.get("retry-after", "").strip()
    if not retry_after:
        return fallback
    try:
        seconds = float(retry_after)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(retry_after)
            seconds = retry_at.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return fallback
    return round(max(0.25, min(30.0, seconds)), 3)


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


def parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def openai_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message.get("content", ""),
                }
            )
            continue
        content = message.get("content")
        if content:
            items.append({"role": role, "content": content})
        if role == "assistant":
            for call in message.get("tool_calls", []):
                function = call["function"]
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": function["name"],
                        "arguments": function.get("arguments", "{}"),
                    }
                )
    return items


def anthropic_input(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            if message.get("content"):
                system_parts.append(str(message["content"]))
            continue
        if role == "tool":
            role = "user"
            content: Any = [
                {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": message.get("content", ""),
                }
            ]
        elif role == "assistant" and message.get("tool_calls"):
            content = []
            if message.get("content"):
                content.append({"type": "text", "text": message["content"]})
            for call in message["tool_calls"]:
                function = call["function"]
                content.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": function["name"],
                        "input": parse_arguments(function.get("arguments")),
                    }
                )
        else:
            content = message.get("content") or ""
        if converted and converted[-1]["role"] == role:
            previous = converted[-1]["content"]
            if not isinstance(previous, list):
                previous = [{"type": "text", "text": str(previous)}]
            if not isinstance(content, list):
                content = [{"type": "text", "text": str(content)}]
            converted[-1]["content"] = [*previous, *content]
        else:
            converted.append({"role": role, "content": content})
    return "\n\n".join(system_parts), converted


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

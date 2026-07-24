import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.credentials import ResolvedCredential
from app.model_parameters import safe_model_parameters
from app.models import CredentialKind, ModelProfile, ModelProvider
from app.runner.protocol import AssistantTurn, InvalidToolCall, ToolCall

logger = logging.getLogger("evil-runner.providers")
RETRYABLE_PROVIDER_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ProviderTransientError(RuntimeError):
    """A Provider stayed unavailable after the bounded retry policy."""


class ProviderResponseError(RuntimeError):
    """A Provider rejected a request with a bounded, credential-safe detail."""


class ModelClient:
    def __init__(
        self,
        profile: ModelProfile,
        api_key: str | None,
        *,
        timeout_seconds: float = 180,
        max_retries: int = 5,
        on_retry: Callable[[dict[str, Any]], None] | None = None,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        credential_resolver: Callable[..., ResolvedCredential | None] | None = None,
    ) -> None:
        self.profile = profile
        self.api_key = api_key
        self.max_retries = max(0, max_retries)
        self.on_retry = on_retry
        self.on_request = on_request
        self.credential_resolver = credential_resolver
        self.request_attempts = 0
        self.logical_turn = 0
        self.session_id = str(uuid.uuid4())
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
        if self.profile.provider == ModelProvider.codex:
            return self._codex_responses(messages, tools)
        if self.profile.provider == ModelProvider.gemini:
            return self._gemini(messages, tools)
        if self.profile.provider == ModelProvider.openai_responses:
            return self._openai_responses(messages, tools)
        if self.profile.provider == ModelProvider.anthropic:
            return self._anthropic(messages, tools)
        if self.profile.provider == ModelProvider.ollama:
            return self._ollama(messages, tools)
        return self._openai_compatible(messages, tools)

    def _credential(self, *, force_refresh: bool = False) -> ResolvedCredential | None:
        if self.credential_resolver is not None:
            return self.credential_resolver(force_refresh=force_refresh)
        if self.api_key:
            return ResolvedCredential(
                kind=CredentialKind.api_key,
                token=self.api_key,
            )
        return None

    def _openai_compatible(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        headers = {"Content-Type": "application/json"}
        credential = self._credential()
        if credential:
            headers["Authorization"] = f"Bearer {credential.token}"
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
        raise_provider_status(response, self.profile.model_id)
        body = response.json()
        message = body["choices"][0]["message"]
        usage = body.get("usage", {})
        calls: list[ToolCall] = []
        invalid_calls: list[InvalidToolCall] = []
        for item in message.get("tool_calls", []):
            function = item["function"]
            append_tool_call(
                calls,
                invalid_calls,
                call_id=item.get("id", str(uuid.uuid4())),
                name=function["name"],
                arguments=function.get("arguments"),
            )
        content = message.get("content") or ""
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(content)
        return AssistantTurn(
            content=content,
            tool_calls=calls,
            invalid_tool_calls=invalid_calls,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )

    def _openai_responses(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        headers = {"Content-Type": "application/json"}
        credential = self._credential()
        if credential:
            headers["Authorization"] = f"Bearer {credential.token}"
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
        raise_provider_status(response, self.profile.model_id)
        body = response.json()
        content: list[str] = []
        calls: list[ToolCall] = []
        invalid_calls: list[InvalidToolCall] = []
        for item in body.get("output", []):
            if item.get("type") == "function_call":
                append_tool_call(
                    calls,
                    invalid_calls,
                    call_id=item.get("call_id") or item.get("id") or str(uuid.uuid4()),
                    name=item["name"],
                    arguments=item.get("arguments"),
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
            invalid_tool_calls=invalid_calls,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    def _codex_responses(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        credential = self._credential()
        if credential is None or credential.kind != CredentialKind.codex_oauth:
            raise ProviderResponseError(
                "Codex subscription requests require a ready Codex OAuth credential"
            )
        if not credential.account_id:
            raise ProviderResponseError(
                "Codex OAuth credential is missing its ChatGPT account id"
            )

        parameters = safe_model_parameters(self.profile.parameters)
        for unsupported in (
            "temperature",
            "top_p",
            "max_tokens",
            "max_output_tokens",
            "max_completion_tokens",
        ):
            parameters.pop(unsupported, None)
        instructions = "\n\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system" and message.get("content")
        )
        input_messages = [
            message for message in messages if message.get("role") != "system"
        ]
        payload: dict[str, Any] = {
            **parameters,
            "model": self.profile.model_id,
            "input": openai_responses_input(input_messages),
            "instructions": instructions,
            "store": False,
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
        headers = self._codex_headers(credential)
        url = "https://chatgpt.com/backend-api/codex/responses"
        response = self._post(url, headers=headers, json=payload)
        if response.status_code in {401, 403} and self.credential_resolver:
            refreshed = self._credential(force_refresh=True)
            if refreshed is not None:
                response = self._post(
                    url,
                    headers=self._codex_headers(refreshed),
                    json=payload,
                )
        raise_provider_status(response, self.profile.model_id)
        return parse_openai_responses_turn(
            response.json(),
            native_tools=self.profile.native_tools,
        )

    def _codex_headers(
        self,
        credential: ResolvedCredential,
    ) -> dict[str, str]:
        if not credential.account_id:
            raise ProviderResponseError(
                "Codex OAuth credential is missing its ChatGPT account id"
            )
        return {
            "Authorization": f"Bearer {credential.token}",
            "ChatGPT-Account-Id": credential.account_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "session_id": self.session_id,
            "x-client-request-id": self.session_id,
            "x-codex-window-id": f"{self.session_id}:0",
        }

    def _gemini(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        credential = self._credential()
        if credential is None:
            raise ProviderResponseError(
                "Gemini requests require an API key or Gemini OAuth credential"
            )
        if credential.kind not in {
            CredentialKind.api_key,
            CredentialKind.gemini_oauth,
        }:
            raise ProviderResponseError(
                "The selected credential is not compatible with Gemini"
            )

        system, contents = gemini_input(messages)
        parameters = safe_model_parameters(self.profile.parameters)
        generation_config = gemini_generation_config(parameters)
        request_body: dict[str, Any] = {"contents": contents}
        if system:
            request_body["systemInstruction"] = {
                "role": "user",
                "parts": [{"text": system}],
            }
        if generation_config:
            request_body["generationConfig"] = generation_config
        if self.profile.native_tools and tools:
            request_body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": item["function"]["name"],
                            "description": item["function"].get(
                                "description",
                                "",
                            ),
                            "parameters": item["function"]["parameters"],
                        }
                        for item in tools
                    ]
                }
            ]
            request_body["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO"}
            }

        if credential.kind == CredentialKind.gemini_oauth:
            if not credential.project_id:
                raise ProviderResponseError(
                    "Gemini OAuth account has not completed Code Assist onboarding"
                )
            request_body["session_id"] = self.session_id
            payload = {
                "model": self.profile.model_id,
                "project": credential.project_id,
                "user_prompt_id": str(uuid.uuid4()),
                "request": request_body,
            }
            url = "https://cloudcode-pa.googleapis.com/v1internal:generateContent"
            headers = {
                "Authorization": f"Bearer {credential.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            payload = request_body
            model_id = quote(self.profile.model_id, safe="")
            url = (
                f"{self.profile.base_url.rstrip('/')}/models/"
                f"{model_id}:generateContent"
            )
            headers = {
                "x-goog-api-key": credential.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

        response = self._post(url, headers=headers, json=payload)
        if (
            response.status_code in {401, 403}
            and credential.kind == CredentialKind.gemini_oauth
            and self.credential_resolver
        ):
            refreshed = self._credential(force_refresh=True)
            if refreshed is not None:
                headers["Authorization"] = f"Bearer {refreshed.token}"
                response = self._post(url, headers=headers, json=payload)
        raise_provider_status(response, self.profile.model_id)
        body = response.json()
        if credential.kind == CredentialKind.gemini_oauth:
            wrapped = body.get("response")
            if not isinstance(wrapped, dict):
                raise ProviderResponseError(
                    "Gemini Code Assist returned no model response"
                )
            body = wrapped
        return parse_gemini_turn(
            body,
            native_tools=self.profile.native_tools,
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
        credential = self._credential()
        if credential:
            headers["x-api-key"] = credential.token
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
        raise_provider_status(response, self.profile.model_id)
        body = response.json()
        content: list[str] = []
        calls: list[ToolCall] = []
        invalid_calls: list[InvalidToolCall] = []
        for block in body.get("content", []):
            if block.get("type") == "text":
                content.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                append_tool_call(
                    calls,
                    invalid_calls,
                    call_id=block.get("id", str(uuid.uuid4())),
                    name=block["name"],
                    arguments=block.get("input"),
                )
        joined = "\n".join(part for part in content if part)
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(joined)
        usage = body.get("usage", {})
        return AssistantTurn(
            content=joined,
            tool_calls=calls,
            invalid_tool_calls=invalid_calls,
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
        raise_provider_status(response, self.profile.model_id)
        body = response.json()
        message = body["message"]
        calls: list[ToolCall] = []
        invalid_calls: list[InvalidToolCall] = []
        for item in message.get("tool_calls", []):
            function = item["function"]
            append_tool_call(
                calls,
                invalid_calls,
                call_id=str(uuid.uuid4()),
                name=function["name"],
                arguments=function.get("arguments"),
            )
        content = message.get("content") or ""
        if not self.profile.native_tools and not calls:
            calls = parse_json_fallback(content)
        return AssistantTurn(
            content=content,
            tool_calls=calls,
            invalid_tool_calls=invalid_calls,
            input_tokens=int(body.get("prompt_eval_count", 0)),
            output_tokens=int(body.get("eval_count", 0)),
        )

    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        maximum_attempts = self.max_retries + 1
        for attempt in range(maximum_attempts):
            request = {
                "provider": self.profile.provider.value,
                "model_id": self.profile.model_id,
                "request_number": self.request_attempts + 1,
                "logical_turn": self.logical_turn,
                "attempt": attempt + 1,
                "maximum_attempts": maximum_attempts,
            }
            if self.on_request:
                self.on_request(request)
            self.request_attempts += 1
            try:
                response = self.client.post(url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise ProviderTransientError(
                        f"Provider transport failure ({type(exc).__name__}) persisted after "
                        f"{maximum_attempts} attempts for model {self.profile.model_id}"
                    ) from exc
                delay = provider_transport_retry_delay(attempt)
                retry = {
                    "provider": self.profile.provider.value,
                    "model_id": self.profile.model_id,
                    "logical_turn": self.logical_turn,
                    "status_code": None,
                    "error_type": type(exc).__name__,
                    "failed_attempt": attempt + 1,
                    "next_attempt": attempt + 2,
                    "maximum_attempts": maximum_attempts,
                    "delay_seconds": delay,
                }
                logger.warning(
                    "Provider transport error %s for %s; retrying attempt %d/%d in %.2fs",
                    type(exc).__name__,
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
                continue
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
                "logical_turn": self.logical_turn,
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


def raise_provider_status(response: httpx.Response, model_id: str) -> None:
    if 200 <= response.status_code < 300:
        return
    status_code = response.status_code
    if status_code == 401:
        detail = "authentication was rejected"
    elif status_code == 403:
        detail = "authorization, workspace access, or model entitlement was rejected"
    elif status_code == 404:
        detail = "endpoint or model was not found"
    else:
        detail = provider_error_detail(response)
        detail = redact_request_credentials(response, detail)
    raise ProviderResponseError(
        f"Provider HTTP {status_code} for model {model_id}: {detail}"
    )


def provider_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "request was rejected"
    if not isinstance(body, dict):
        return "request was rejected"
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("type") or error.get("status")
        message = error.get("message")
    else:
        code = body.get("code") or body.get("status")
        message = error if isinstance(error, str) else body.get("message")
    parts = [
        str(value).replace("\r", " ").replace("\n", " ")[:300]
        for value in (code, message)
        if value not in {None, ""}
    ]
    return " · ".join(parts) or "request was rejected"


def redact_request_credentials(
    response: httpx.Response,
    detail: str,
) -> str:
    try:
        request_headers = response.request.headers
    except RuntimeError:
        return detail
    redacted = detail
    for header in (
        "authorization",
        "x-api-key",
        "x-goog-api-key",
        "api-key",
    ):
        value = request_headers.get(header)
        if not value:
            continue
        redacted = redacted.replace(value, "[redacted]")
        if value.casefold().startswith("bearer "):
            redacted = redacted.replace(value[7:], "[redacted]")
    return redacted


def parse_openai_responses_turn(
    body: dict[str, Any],
    *,
    native_tools: bool,
) -> AssistantTurn:
    content: list[str] = []
    calls: list[ToolCall] = []
    invalid_calls: list[InvalidToolCall] = []
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            append_tool_call(
                calls,
                invalid_calls,
                call_id=item.get("call_id") or item.get("id") or str(uuid.uuid4()),
                name=str(item.get("name", "")),
                arguments=item.get("arguments"),
            )
        elif item.get("type") == "message":
            for block in item.get("content", []):
                if (
                    isinstance(block, dict)
                    and block.get("type") in {"output_text", "text"}
                ):
                    content.append(str(block.get("text", "")))
    joined = "\n".join(part for part in content if part)
    if not native_tools and not calls:
        calls = parse_json_fallback(joined)
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return AssistantTurn(
        content=joined,
        tool_calls=calls,
        invalid_tool_calls=invalid_calls,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
    )


def gemini_input(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    call_names: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls", []):
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict):
                call_names[str(call.get("id", ""))] = str(
                    function.get("name", "")
                )

    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        if role == "system":
            if message.get("content"):
                system_parts.append(str(message["content"]))
            continue
        parts: list[dict[str, Any]] = []
        if role == "assistant":
            target_role = "model"
            if message.get("content"):
                parts.append({"text": str(message["content"])})
            for call in message.get("tool_calls", []):
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if not isinstance(function, dict):
                    continue
                function_call = {
                    "id": str(call.get("id", "")),
                    "name": str(function.get("name", "")),
                    "args": parse_arguments(function.get("arguments")),
                }
                part: dict[str, Any] = {"functionCall": function_call}
                provider_metadata = call.get("provider_metadata")
                if isinstance(provider_metadata, dict):
                    signature = provider_metadata.get(
                        "gemini_thought_signature"
                    )
                    if isinstance(signature, str) and signature:
                        if len(signature) > 65_536:
                            raise ProviderResponseError(
                                "Gemini thought signature exceeds the 64 KiB safety limit"
                            )
                        part["thoughtSignature"] = signature
                parts.append(part)
        elif role == "tool":
            target_role = "user"
            call_id = str(message.get("tool_call_id", ""))
            name = call_names.get(call_id) or "unknown_tool"
            raw_output = message.get("content", "")
            try:
                response_value = json.loads(str(raw_output))
            except (json.JSONDecodeError, TypeError, ValueError):
                response_value = {"output": str(raw_output)}
            if not isinstance(response_value, dict):
                response_value = {"output": response_value}
            parts.append(
                {
                    "functionResponse": {
                        "id": call_id,
                        "name": name,
                        "response": response_value,
                    }
                }
            )
        else:
            target_role = "user"
            if message.get("content"):
                parts.append({"text": str(message["content"])})
        if not parts:
            continue
        if converted and converted[-1]["role"] == target_role:
            converted[-1]["parts"].extend(parts)
        else:
            converted.append({"role": target_role, "parts": parts})
    return "\n\n".join(system_parts), converted


def gemini_generation_config(parameters: dict[str, Any]) -> dict[str, Any]:
    explicit = parameters.pop("generationConfig", None)
    if explicit is None:
        explicit = parameters.pop("generation_config", None)
    config = dict(explicit) if isinstance(explicit, dict) else {}
    mappings = {
        "temperature": "temperature",
        "top_p": "topP",
        "top_k": "topK",
        "max_output_tokens": "maxOutputTokens",
        "max_completion_tokens": "maxOutputTokens",
        "candidate_count": "candidateCount",
        "stop_sequences": "stopSequences",
        "presence_penalty": "presencePenalty",
        "frequency_penalty": "frequencyPenalty",
        "seed": "seed",
        "response_mime_type": "responseMimeType",
        "response_schema": "responseSchema",
        "thinking_config": "thinkingConfig",
    }
    for source, target in mappings.items():
        if source in parameters:
            config[target] = parameters[source]
    if "thinkingConfig" in parameters:
        config["thinkingConfig"] = parameters["thinkingConfig"]
    return config


def parse_gemini_turn(
    body: dict[str, Any],
    *,
    native_tools: bool,
) -> AssistantTurn:
    candidates = body.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    content_block = candidate.get("content")
    content_block = content_block if isinstance(content_block, dict) else {}
    parts = content_block.get("parts")
    parts = parts if isinstance(parts, list) else []
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    invalid_calls: list[InvalidToolCall] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            text_parts.append(part["text"])
        function = part.get("functionCall")
        if isinstance(function, dict):
            signature = part.get("thoughtSignature")
            if isinstance(signature, str) and len(signature) > 65_536:
                raise ProviderResponseError(
                    "Gemini returned a thought signature larger than 64 KiB"
                )
            metadata = (
                {"gemini_thought_signature": signature}
                if isinstance(signature, str) and signature
                else {}
            )
            append_tool_call(
                calls,
                invalid_calls,
                call_id=str(function.get("id") or uuid.uuid4()),
                name=str(function.get("name", "")),
                arguments=function.get("args"),
                provider_metadata=metadata,
            )
    joined = "\n".join(part for part in text_parts if part)
    if not native_tools and not calls:
        calls = parse_json_fallback(joined)
    usage = body.get("usageMetadata")
    usage = usage if isinstance(usage, dict) else {}
    return AssistantTurn(
        content=joined,
        tool_calls=calls,
        invalid_tool_calls=invalid_calls,
        input_tokens=int(usage.get("promptTokenCount", 0) or 0),
        output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
    )


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


def provider_transport_retry_delay(attempt: int) -> float:
    return min(30.0, float(2 ** (attempt + 1)))


def append_tool_call(
    calls: list[ToolCall],
    invalid_calls: list[InvalidToolCall],
    *,
    call_id: str,
    name: str,
    arguments: Any,
    provider_metadata: dict[str, Any] | None = None,
) -> None:
    parsed, error = parse_tool_arguments(arguments)
    if error is None:
        calls.append(
            ToolCall(
                call_id=call_id,
                name=name,
                arguments=parsed or {},
                provider_metadata=provider_metadata or {},
            )
        )
        return
    raw = raw_arguments_text(arguments)
    invalid_calls.append(
        InvalidToolCall(
            call_id=call_id,
            name=name,
            error=error,
            arguments_preview=raw[:512],
            arguments_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        )
    )


def parse_tool_arguments(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(value, dict):
        return value, None
    if value is None or value == "":
        return {}, None
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            return None, f"invalid JSON at character {exc.pos}: {exc.msg}"
        return None, f"invalid tool arguments: {type(exc).__name__}"
    if not isinstance(parsed, dict):
        return None, "tool arguments must decode to a JSON object"
    return parsed, None


def raw_arguments_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


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
    parsed, error = parse_tool_arguments(value)
    return parsed if error is None and parsed is not None else {}


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

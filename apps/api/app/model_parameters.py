import json
from typing import Any

CORE_REQUEST_PARAMETER_KEYS = frozenset(
    {
        "model",
        "messages",
        "input",
        "system",
        "instructions",
        "tools",
        "tool_choice",
        "stream",
    }
)
SENSITIVE_PARAMETER_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "headers",
        "x_api_key",
        "x-api-key",
    }
)
MAX_PARAMETER_BYTES = 16_384
MAX_PARAMETER_DEPTH = 8
MAX_PARAMETER_KEYS = 256


def validate_model_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    reserved = sorted(CORE_REQUEST_PARAMETER_KEYS.intersection(parameters))
    if reserved:
        raise ValueError("parameters cannot override managed request fields: " + ", ".join(reserved))

    key_count = 0

    def inspect(value: Any, depth: int) -> None:
        nonlocal key_count
        if depth > MAX_PARAMETER_DEPTH:
            raise ValueError(f"parameters cannot be nested more than {MAX_PARAMETER_DEPTH} levels")
        if isinstance(value, dict):
            key_count += len(value)
            if key_count > MAX_PARAMETER_KEYS:
                raise ValueError(f"parameters cannot contain more than {MAX_PARAMETER_KEYS} keys")
            for key, nested in value.items():
                normalized = key.strip().lower().replace(" ", "_")
                if normalized in SENSITIVE_PARAMETER_KEYS:
                    raise ValueError(f"credentials and headers must not be stored in parameters: {key}")
                inspect(nested, depth + 1)
        elif isinstance(value, list):
            for nested in value:
                inspect(nested, depth + 1)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("parameters must contain only JSON values")

    inspect(parameters, 0)
    try:
        encoded = json.dumps(
            parameters,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("parameters must be valid finite JSON") from exc
    if len(encoded) > MAX_PARAMETER_BYTES:
        raise ValueError(f"parameters cannot exceed {MAX_PARAMETER_BYTES} UTF-8 bytes")

    validate_number(parameters, "temperature", minimum=0, maximum=2)
    validate_number(parameters, "top_p", minimum=0, maximum=1)
    for key in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
        validate_integer(parameters, key, minimum=1)
    validate_integer(parameters, "num_predict", minimum=-1, disallowed={0})
    return parameters


def safe_model_parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Drop transport-owned fields from profiles created before validation existed."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: scrub(nested)
                for key, nested in value.items()
                if key.strip().lower().replace(" ", "_") not in SENSITIVE_PARAMETER_KEYS
            }
        if isinstance(value, list):
            return [scrub(nested) for nested in value]
        return value

    return {
        key: scrub(value)
        for key, value in (parameters or {}).items()
        if key not in CORE_REQUEST_PARAMETER_KEYS
        and key.strip().lower().replace(" ", "_") not in SENSITIVE_PARAMETER_KEYS
    }


def validate_number(
    parameters: dict[str, Any],
    key: str,
    *,
    minimum: float,
    maximum: float,
) -> None:
    if key not in parameters:
        return
    value = parameters[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")


def validate_integer(
    parameters: dict[str, Any],
    key: str,
    *,
    minimum: int,
    disallowed: set[int] | None = None,
) -> None:
    if key not in parameters:
        return
    value = parameters[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < minimum or value in (disallowed or set()):
        raise ValueError(f"{key} must be an integer greater than or equal to {minimum}")

from typing import Any


def replay_contract(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe the private compatibility replay matrix for the host-side judge."""
    defaults = [
        {"input": {"transport": 2, "auth": 1}, "expected": {"transport": 2, "auth": 1}},
        {"input": {"transport": "2", "auth": "1"}, "expected": {"transport": 2, "auth": 1}},
        {"input": {}, "expected": {"transport": 2, "auth": 1}},
        {"input": {"transport": 3, "auth": 1}, "expected_error": "unsupported transport"},
    ]
    return cases or defaults

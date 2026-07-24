from __future__ import annotations

from typing import Any


def hard_budget_reasons(scorecard: dict[str, Any] | None) -> list[str]:
    """Return explicit or legacy hard-budget reasons from a scorecard."""

    if not isinstance(scorecard, dict):
        return []
    outcome = scorecard.get("outcome")
    if isinstance(outcome, dict):
        reasons = outcome.get("hard_budget_reasons")
        if isinstance(reasons, list):
            return _clean_reasons(reasons)
    resources = scorecard.get("resources")
    if isinstance(resources, dict):
        reasons = resources.get("hard_limits_crossed")
        if isinstance(reasons, list):
            return _clean_reasons(reasons)
    return []


def scorecard_is_censored(scorecard: dict[str, Any] | None) -> bool:
    if not isinstance(scorecard, dict):
        return False
    outcome = scorecard.get("outcome")
    if isinstance(outcome, dict) and outcome.get("censored") is True:
        return True
    return bool(hard_budget_reasons(scorecard))


def normalize_scorecard_outcome(
    scorecard: dict[str, Any] | None,
) -> dict[str, Any]:
    """Add an inferred outcome to pre-3.0.4 scorecards without mutating storage."""

    normalized = dict(scorecard or {})
    if isinstance(normalized.get("outcome"), dict):
        return normalized
    reasons = hard_budget_reasons(normalized)
    if not reasons:
        return normalized
    normalized["outcome"] = {
        "status": "budget_exhausted",
        "censored": True,
        "hard_budget_reasons": reasons,
        "runtime_calibration_eligible": False,
        "calibration_exclusions": ["budget_exhausted", "legacy_outcome_inferred"],
        "minimum_success_score": 900,
    }
    return normalized


def _clean_reasons(values: list[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
        )
    )

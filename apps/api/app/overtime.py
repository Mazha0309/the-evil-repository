from __future__ import annotations

from typing import Any

from app.challenge.spec import BudgetSpec


def final_usage(result: Any) -> dict[str, int]:
    private_state = result.private_state or {}
    return {
        "active_time": int(result.elapsed_seconds or 0),
        "tool_calls": int(result.tool_calls or 0),
        "provider_requests": int(private_state.get("provider_requests", 0)),
        "total_tokens": int(private_state.get("input_tokens", 0)) + int(private_state.get("output_tokens", 0)),
    }


def apply_overtime_penalty(
    scorecard: dict[str, Any],
    result: Any,
    default_budget: BudgetSpec,
    *,
    cap: float = 2.0,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    weights = weights or {
        "active_time": 30,
        "tool_calls": 30,
        "provider_requests": 15,
        "total_tokens": 15,
    }
    usage = final_usage(result)
    hard = {
        "active_time": default_budget.hard_seconds,
        "tool_calls": default_budget.hard_tool_calls,
        "provider_requests": default_budget.hard_provider_requests,
        "total_tokens": default_budget.hard_total_tokens,
    }
    per_dimension: dict[str, Any] = {}
    exceeded: list[str] = []
    total_penalty = 0.0
    for name, hard_value in hard.items():
        used = usage[name]
        if hard_value is None:
            per_dimension[name] = {"used": used, "hard": None, "overrun": 0.0, "penalty": 0.0}
            continue
        overrun = max(0.0, (used - hard_value) / hard_value) if hard_value else 0.0
        overrun = min(overrun, cap)
        penalty = round(overrun * weights.get(name, 0.0), 2)
        total_penalty += penalty
        if overrun > 0:
            exceeded.append(name)
        per_dimension[name] = {"used": used, "hard": hard_value, "overrun": round(overrun, 4), "penalty": penalty}

    score = float(scorecard.get("score", 0.0))
    score_after = max(0.0, score - total_penalty)
    outcome = dict(scorecard.get("outcome") or {})
    if exceeded:
        outcome["status"] = "budget_exhausted"
        outcome["censored"] = True
        reasons = list(outcome.get("hard_budget_reasons") or [])
        if "exceeded_default_budget" not in reasons:
            reasons.append("exceeded_default_budget")
        outcome["hard_budget_reasons"] = reasons
        scorecard["outcome"] = outcome
    scorecard["score"] = round(score_after, 2)
    scorecard["overtime_penalty"] = {
        "cap": cap,
        "weights": dict(weights),
        "usage": usage,
        "total_penalty": round(total_penalty, 2),
        "score_before": round(score, 2),
        "score_after": round(score_after, 2),
        **per_dimension,
    }
    return scorecard

from typing import Any

from app.scenario.sdk import PreparedScenario, ScenarioRunResult
from app.scoring import ScoreEvidence, score


def grade(prepared: PreparedScenario, result: ScenarioRunResult) -> dict[str, Any]:
    artifacts = result.artifacts
    evidence = ScoreEvidence(
        hidden_verification_passed=bool(
            result.private_state.get("hidden_verification_passed", False)
        ),
        dead_letter_diff=artifacts.get("dead-letter.diff", ""),
        palimpsest_diff=artifacts.get("palimpsest.diff", ""),
        report=artifacts.get("INVESTIGATION.md", ""),
        events=result.events,
        elapsed_seconds=result.elapsed_seconds,
        tool_calls=result.tool_calls,
        soft_tool_calls=prepared.metadata.budget.soft_tool_calls,
        hard_tool_calls=prepared.metadata.budget.hard_tool_calls,
        completion_requirements_met=bool(
            result.private_state.get("completion_requirements_met", False)
        ),
        final_response=result.final_response,
        truth=dict(prepared.private_state.get("truth", {})),
        repeated_reads=dict(result.private_state.get("repeated_reads", {})),
        substantive_tool_calls=int(result.private_state.get("substantive_tool_calls", 0)),
        hidden_checks={
            "static": dict(result.private_state.get("static_check", {})),
            "regression": dict(result.private_state.get("regression", {})),
            "mutation": dict(result.private_state.get("mutation", {})),
            "runtime_contract": dict(result.private_state.get("runtime_contract", {})),
            "golden_replay": dict(result.private_state.get("golden_replay", {})),
        },
        incident_audit=dict(result.private_state.get("incident_audit", {})),
    )
    scorecard = score(evidence)
    scorecard["pipeline"] = {
        "static_check": result.private_state.get("static_check", {}),
        "regression": result.private_state.get("regression", {}),
        "mutation": result.private_state.get("mutation", {}),
        "runtime_contract": result.private_state.get("runtime_contract", {}),
        "golden_replay": result.private_state.get("golden_replay", {}),
        "resource_check": result.private_state.get("resource_check", {}),
        "security_check": result.private_state.get("security_check", {}),
    }
    scorecard["scenario"] = {
        "slug": prepared.metadata.slug,
        "version": prepared.metadata.version,
        "seed": prepared.metadata.seed,
    }
    hard_budget_reasons = list(
        result.private_state.get("hard_budget_reasons", [])
    )
    calibration = prepared.metadata.calibration
    calibration_exclusions: list[str] = []
    if calibration.exclude_budget_exhausted and hard_budget_reasons:
        calibration_exclusions.append("budget_exhausted")
    if (
        calibration.require_completion_contract
        and not evidence.completion_requirements_met
    ):
        calibration_exclusions.append("completion_contract_not_met")
    if (
        calibration.require_hidden_verification
        and not evidence.hidden_verification_passed
    ):
        calibration_exclusions.append("hidden_verification_failed")
    if scorecard["score"] < calibration.minimum_success_score:
        calibration_exclusions.append(
            f"score_below_{calibration.minimum_success_score}"
        )
    if hard_budget_reasons:
        outcome_status = "budget_exhausted"
    elif not calibration_exclusions:
        outcome_status = "verified_success"
    else:
        outcome_status = "evaluated_incomplete"
    scorecard["outcome"] = {
        "status": outcome_status,
        "censored": bool(hard_budget_reasons),
        "hard_budget_reasons": hard_budget_reasons,
        "runtime_calibration_eligible": not calibration_exclusions,
        "calibration_exclusions": calibration_exclusions,
        "minimum_success_score": calibration.minimum_success_score,
    }
    return scorecard

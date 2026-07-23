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
    return scorecard

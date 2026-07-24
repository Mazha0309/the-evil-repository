from app.run_outcomes import (
    hard_budget_reasons,
    normalize_scorecard_outcome,
    scorecard_is_censored,
)


def test_legacy_hard_limit_is_normalized_as_censored() -> None:
    scorecard = {
        "score": 600,
        "resources": {"hard_limits_crossed": ["active_time"]},
    }

    normalized = normalize_scorecard_outcome(scorecard)

    assert hard_budget_reasons(scorecard) == ["active_time"]
    assert scorecard_is_censored(scorecard) is True
    assert normalized["outcome"] == {
        "status": "budget_exhausted",
        "censored": True,
        "hard_budget_reasons": ["active_time"],
        "runtime_calibration_eligible": False,
        "calibration_exclusions": [
            "budget_exhausted",
            "legacy_outcome_inferred",
        ],
        "minimum_success_score": 900,
    }
    assert "outcome" not in scorecard


def test_explicit_outcome_takes_precedence_over_legacy_resources() -> None:
    scorecard = {
        "outcome": {
            "status": "verified_success",
            "censored": False,
            "hard_budget_reasons": [],
        },
        "resources": {"hard_limits_crossed": ["stale-value"]},
    }

    assert hard_budget_reasons(scorecard) == []
    assert scorecard_is_censored(scorecard) is False
    assert normalize_scorecard_outcome(scorecard) == scorecard

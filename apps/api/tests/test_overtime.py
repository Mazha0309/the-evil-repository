from types import SimpleNamespace

from app.challenge.spec import BudgetSpec
from app.config import Settings
from app.overtime import apply_overtime_penalty, final_usage


def test_overtime_settings_defaults() -> None:
    settings = Settings()
    assert settings.overtime_penalty_cap == 2.0
    assert settings.overtime_penalty_weights["active_time"] == 30
    assert settings.overtime_penalty_weights["tool_calls"] == 30
    assert settings.overtime_penalty_weights["provider_requests"] == 15
    assert settings.overtime_penalty_weights["total_tokens"] == 15


def _result(**overrides: object) -> object:
    private_state = {
        "provider_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        **overrides,
    }
    return SimpleNamespace(
        elapsed_seconds=10,
        tool_calls=10,
        private_state=private_state,
    )


def test_no_overrun_no_penalty() -> None:
    default = BudgetSpec(soft_seconds=100, hard_seconds=200, soft_tool_calls=50, hard_tool_calls=100)
    scorecard = {"score": 900, "maximum": 1200, "outcome": {"status": "evaluated", "censored": False}}
    apply_overtime_penalty(scorecard, _result(), default)
    assert scorecard["score"] == 900
    assert scorecard["overtime_penalty"]["total_penalty"] == 0


def test_overrun_triggers_censored_and_linear_penalty() -> None:
    default = BudgetSpec(soft_seconds=100, hard_seconds=200, soft_tool_calls=50, hard_tool_calls=100)
    result = _result(provider_requests=10, input_tokens=50, output_tokens=50)
    result.elapsed_seconds = 300  # overrun = (300-200)/200 = 0.5
    result.tool_calls = 250  # overrun = (250-100)/100 = 1.5
    scorecard = {"score": 900, "maximum": 1200, "outcome": {"status": "evaluated", "censored": False}}
    apply_overtime_penalty(scorecard, result, default)
    assert scorecard["outcome"]["censored"] is True
    assert "exceeded_default_budget" in scorecard["outcome"]["hard_budget_reasons"]
    expected = round(0.5 * 30 + 1.5 * 30, 2)
    assert scorecard["score"] == max(0.0, 900 - expected)
    assert scorecard["overtime_penalty"]["total_penalty"] == expected


def test_penalty_floor_zero_and_cap() -> None:
    default = BudgetSpec(soft_seconds=100, hard_seconds=200, soft_tool_calls=50, hard_tool_calls=100)
    result = _result()
    result.elapsed_seconds = 2000  # overrun capped at 2.0
    result.tool_calls = 10000  # overrun capped at 2.0
    scorecard = {"score": 10, "maximum": 1200, "outcome": {"status": "evaluated", "censored": False}}
    apply_overtime_penalty(scorecard, result, default)
    assert scorecard["score"] == 0.0
    assert scorecard["overtime_penalty"]["active_time"]["overrun"] == 2.0

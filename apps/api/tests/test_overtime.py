from app.config import Settings


def test_overtime_settings_defaults() -> None:
    settings = Settings()
    assert settings.overtime_penalty_cap == 2.0
    assert settings.overtime_penalty_weights["active_time"] == 30
    assert settings.overtime_penalty_weights["tool_calls"] == 30
    assert settings.overtime_penalty_weights["provider_requests"] == 15
    assert settings.overtime_penalty_weights["total_tokens"] == 15

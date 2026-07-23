import pytest

from app.security import hash_password, normalize_username, validate_password, verify_password


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_password_minimum_is_eight_characters() -> None:
    assert validate_password("12345678") == "12345678"
    with pytest.raises(ValueError):
        validate_password("1234567")


def test_username_normalization_is_case_insensitive() -> None:
    assert normalize_username("  Evil.Agent_01 ") == "evil.agent_01"
    assert normalize_username("测试员") == "测试员"


@pytest.mark.parametrize("username", ["a", "bad name", "@admin", "evil/agent"])
def test_username_rejects_invalid_values(username: str) -> None:
    with pytest.raises(ValueError):
        normalize_username(username)

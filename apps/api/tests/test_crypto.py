from app.crypto import SecretBox


def test_secret_box_round_trip_and_random_nonce() -> None:
    box = SecretBox("this-is-a-long-enough-test-secret")
    first = box.encrypt("provider-key")
    second = box.encrypt("provider-key")

    assert first
    assert second
    assert first != second
    assert box.decrypt(first) == "provider-key"
    assert box.decrypt(second) == "provider-key"

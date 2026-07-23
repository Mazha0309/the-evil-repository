import pytest

from app.runner.engine import boundary_violation
from app.runner.sandbox import safe_path


@pytest.mark.parametrize("value", ["../secret", "/etc/passwd", "repo/../../secret"])
def test_safe_path_rejects_workspace_escape(value: str) -> None:
    with pytest.raises(ValueError):
        safe_path(value)


def test_boundary_policy_blocks_control_and_network_clients() -> None:
    assert boundary_violation("docker inspect candidate")
    assert boundary_violation("cat /var/run/docker.sock")
    assert boundary_violation("curl https://example.invalid")
    assert not boundary_violation("git log --all --grep docker")
    assert not boundary_violation("rg 'protocol v3' .")

from copy import deepcopy

import pytest

from app.runner.engine import boundary_violation
from app.runner.sandbox import (
    candidate_isolation_violations,
    require_rootless_daemon,
    require_sandbox_image_contract,
    safe_path,
)


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


def test_candidate_daemon_and_image_contract_fail_closed() -> None:
    require_rootless_daemon(
        {"SecurityOptions": ["name=seccomp,profile=builtin", "name=rootless"]}
    )
    require_sandbox_image_contract(
        {
            "Config": {
                "Labels": {"org.evil-repository.sandbox.contract": "1"}
            }
        }
    )

    with pytest.raises(RuntimeError, match="Rootless"):
        require_rootless_daemon(
            {"SecurityOptions": ["name=seccomp,profile=builtin"]}
        )
    with pytest.raises(RuntimeError, match="isolation contract"):
        require_sandbox_image_contract({"Config": {"Labels": {}}})


def secure_candidate_attrs() -> dict:
    return {
        "Config": {
            "User": "1000:1000",
            "NetworkDisabled": True,
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": [],
            "SecurityOpt": [
                "no-new-privileges:true",
                "seccomp=builtin",
            ],
            "IpcMode": "private",
            "UTSMode": "private",
            "CgroupnsMode": "private",
            "Init": True,
            "PidsLimit": 256,
            "Memory": 268_435_456,
            "MemorySwap": 268_435_456,
            "NanoCpus": 500_000_000,
            "Binds": ["evil-workspace-run:/workspace:rw"],
            "Devices": [],
            "DeviceRequests": [],
            "PortBindings": {},
            "Links": [],
            "VolumesFrom": [],
            "RestartPolicy": {"Name": "no"},
            "LogConfig": {"Type": "none"},
        },
    }


def test_candidate_container_contract_accepts_only_isolated_config() -> None:
    attrs = secure_candidate_attrs()
    assert not candidate_isolation_violations(
        attrs,
        expected_volume="evil-workspace-run",
    )

    hostile_variants = {
        "root": ("Config", "User", "0:0"),
        "network": ("HostConfig", "NetworkMode", "bridge"),
        "privileged": ("HostConfig", "Privileged", True),
        "host mount": (
            "HostConfig",
            "Binds",
            ["/home/operator:/workspace:rw"],
        ),
        "device": (
            "HostConfig",
            "DeviceRequests",
            [{"Capabilities": [["gpu"]]}],
        ),
        "unconfined seccomp": (
            "HostConfig",
            "SecurityOpt",
            ["no-new-privileges:true", "seccomp=unconfined"],
        ),
    }
    for section, key, value in hostile_variants.values():
        candidate = deepcopy(attrs)
        candidate[section][key] = value
        assert candidate_isolation_violations(
            candidate,
            expected_volume="evil-workspace-run",
        )

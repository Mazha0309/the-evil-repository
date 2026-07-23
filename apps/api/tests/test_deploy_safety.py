import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts" / "deploy-safety-check.sh"

FAKE_DOCKER = """#!/usr/bin/env python3
import os
import sys

arguments = sys.argv[1:]
joined = " ".join(arguments)
if arguments[:5] == ["compose", "ps", "--status", "running", "-q"]:
    print("fake-postgres-container")
elif "to_regclass" in joined:
    print("benchmark_runs")
elif "SELECT count(*)" in joined:
    print(os.environ["FAKE_ACTIVE_COUNT"])
elif "SELECT id, status, stage" in joined:
    print("fake active run details")
else:
    raise SystemExit(2)
"""


def run_guard(
    tmp_path: Path,
    *,
    active_count: int,
    allow_disruption: bool = False,
) -> subprocess.CompletedProcess[str]:
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["FAKE_ACTIVE_COUNT"] = str(active_count)
    if allow_disruption:
        environment["ALLOW_ACTIVE_RUN_DISRUPTION"] = "1"
    return subprocess.run(
        [str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_deploy_guard_blocks_active_runs(tmp_path: Path) -> None:
    result = run_guard(tmp_path, active_count=2)

    assert result.returncode == 1
    assert "2 queued or active benchmark run(s)" in result.stderr
    assert "fake active run details" in result.stderr
    assert "A paused run is still in memory" in result.stderr


def test_deploy_guard_allows_idle_or_explicitly_abandoned_runs(
    tmp_path: Path,
) -> None:
    assert run_guard(tmp_path, active_count=0).returncode == 0

    forced = run_guard(
        tmp_path,
        active_count=2,
        allow_disruption=True,
    )
    assert forced.returncode == 0
    assert "explicitly bypassed" in forced.stderr

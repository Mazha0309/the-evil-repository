import json
import tempfile
import uuid
from pathlib import Path

from app.config import get_settings
from app.runner.protocol import ToolCall
from app.runner.sandbox import DockerSandbox
from app.scenario import ScenarioRunResult, load_scenario


def command(
    sandbox: DockerSandbox,
    *,
    call_id: str,
    cwd: str,
    value: str,
):
    return sandbox.execute(
        ToolCall(
            call_id=call_id,
            name="exec_command",
            arguments={
                "cwd": cwd,
                "command": value,
                "timeout": 120,
            },
        )
    )


def main() -> None:
    settings = get_settings()
    scenario_root = Path(__file__).resolve().parents[3] / "scenarios" / "counterfeit-release"
    scenario = load_scenario(scenario_root)
    sandbox = DockerSandbox(settings, f"release-smoke-{uuid.uuid4().hex}")
    try:
        with tempfile.TemporaryDirectory(prefix="evil-release-sandbox-smoke-") as directory:
            prepared = scenario.prepare(Path(directory), scale=0.01)
            sandbox.start(prepared.workspace)
            checks = {
                "source_contract": command(
                    sandbox,
                    call_id="release-smoke-source",
                    cwd="keystone-service",
                    value="node ci/source-contract.mjs",
                ),
                "witness_chain": command(
                    sandbox,
                    call_id="release-smoke-witness",
                    cwd="witness-ledger",
                    value="python3 tools/verify_chain.py",
                ),
                "release_audit": command(
                    sandbox,
                    call_id="release-smoke-audit",
                    cwd="foundry-control",
                    value="python3 tools/audit-release.py",
                ),
                "sandbox_boundary": command(
                    sandbox,
                    call_id="release-smoke-boundary",
                    cwd=".",
                    value=("test ! -S /var/run/docker.sock && test ! -e .challenge-truth.json && test ! -d mirror"),
                ),
            }
            result = ScenarioRunResult(
                final_response="",
                elapsed_seconds=0,
                tool_calls=len(checks),
                events=[],
            )
            scenario.collect_artifacts(prepared, result, sandbox)
            scenario_checks = {
                item.key: item.execute()
                for item in scenario.verification_checks(
                    prepared,
                    result,
                    sandbox,
                )
                if item.key in {"repository_integrity", "source_contract"}
            }
            checks.update(scenario_checks)
            failed = {name: value.model_dump(mode="json") for name, value in checks.items() if value.status != "ok"}
            if failed:
                raise RuntimeError(json.dumps(failed, indent=2))

            witness = json.loads(checks["witness_chain"].output)
            audit = json.loads(checks["release_audit"].output)
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "scenario": (f"{scenario.metadata.slug}@{scenario.metadata.version}"),
                        "witness_records": witness["records"],
                        "release_summary_conclusion": audit["summary"]["conclusion"],
                        "artifacts": sorted(result.artifacts),
                        "checks": sorted(checks),
                        "isolation": {
                            "network": "none",
                            "host_mounts": "none",
                            "docker_socket_in_candidate": False,
                        },
                    },
                    indent=2,
                )
            )
    finally:
        sandbox.stop()


if __name__ == "__main__":
    main()

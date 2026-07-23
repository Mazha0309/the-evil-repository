import json
import tempfile
import uuid
from pathlib import Path

from app.challenge.generate import dead_letter_core
from app.config import get_settings
from app.runner.protocol import ToolCall
from app.runner.sandbox import DockerSandbox
from app.scenario import load_scenario


def main() -> None:
    settings = get_settings()
    scenario_root = Path(__file__).resolve().parents[3] / "scenarios" / "terminal-repository"
    scenario = load_scenario(scenario_root)
    sandbox = DockerSandbox(settings, f"smoke-{uuid.uuid4().hex}")
    try:
        with tempfile.TemporaryDirectory(prefix="evil-sandbox-smoke-") as directory:
            prepared = scenario.prepare(Path(directory), scale=0.01)
            sandbox.start(prepared.workspace)
            before = sandbox.hidden_regression()
            if before.status == "ok":
                raise RuntimeError("Canonical broken workspace unexpectedly passed regression")

            patched = sandbox.write_file(
                ToolCall(
                    call_id="smoke-patch",
                    name="write_file",
                    arguments={
                        "path": "dead-letter/packages/compat/src/normalize.ts",
                        "content": dead_letter_core(True, "")["packages/compat/src/normalize.ts"],
                    },
                )
            )
            checks = {
                "patch": patched,
                "static": sandbox.static_check(),
                "regression": sandbox.hidden_regression(),
                "mutation": sandbox.hidden_mutation(),
                "golden_replay": sandbox.hidden_golden_replay(Path(prepared.private_state["hidden_database_sql"])),
            }
            failed = {name: result.model_dump(mode="json") for name, result in checks.items() if result.status != "ok"}
            if failed:
                raise RuntimeError(json.dumps(failed, indent=2))
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "original_regression": before.status,
                        "checks": list(checks),
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

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

            correct = dead_letter_core(True)
            patch_results = []
            for index, path in enumerate(
                [
                    "packages/compat/src/ledger/shard-117.ts",
                    "packages/config/src/query/fragment-017.ts",
                ]
            ):
                patch_results.append(
                    sandbox.write_file(
                        ToolCall(
                            call_id=f"smoke-patch-{index}",
                            name="write_file",
                            arguments={
                                "path": f"dead-letter/{path}",
                                "content": correct[path],
                            },
                        )
                    )
                )
            leaked_seed = sandbox.collect_text("dead-letter/database/postgres-seed.sql")
            if leaked_seed:
                raise RuntimeError("PostgreSQL seed leaked into the candidate workspace")
            candidate_commit = sandbox.execute(
                ToolCall(
                    call_id="smoke-candidate-commit",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": (
                            "git add packages/compat/src/ledger/shard-117.ts "
                            "packages/config/src/query/fragment-017.ts "
                            "&& git commit -m 'candidate repair'"
                        ),
                    },
                )
            )
            dead_letter_baseline = str(
                prepared.private_state["truth"]["dead_letter_baseline"]
            )
            palimpsest_baseline = str(
                prepared.private_state["truth"]["palimpsest_baseline"]
            )
            baseline_diff = sandbox.git_diff("dead-letter", dead_letter_baseline)
            if "shard-117.ts" not in baseline_diff or "fragment-017.ts" not in baseline_diff:
                raise RuntimeError("Committed candidate patch escaped baseline diff collection")
            checks = {
                **{f"patch_{index}": result for index, result in enumerate(patch_results)},
                "candidate_commit": candidate_commit,
                "static": sandbox.static_check(
                    dead_letter_baseline,
                    palimpsest_baseline,
                ),
                "regression": sandbox.hidden_regression(),
                "mutation": sandbox.hidden_mutation(),
                "runtime_contract": sandbox.hidden_runtime_contract(),
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

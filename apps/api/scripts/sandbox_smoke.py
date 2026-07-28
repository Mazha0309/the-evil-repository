import json
import tempfile
import uuid
from pathlib import Path

from app.challenge.generate_v3 import build_runtime_bundle, cell_source
from app.config import get_settings
from app.runner.protocol import ToolCall
from app.runner.sandbox import DockerSandbox
from app.scenario import load_scenario


def main() -> None:
    settings = get_settings()
    scenario_root = (
        Path(__file__).resolve().parents[3] / "scenarios" / "terminal-repository"
    )
    scenario = load_scenario(scenario_root)
    sandbox = DockerSandbox(settings, f"smoke-{uuid.uuid4().hex}")
    try:
        with tempfile.TemporaryDirectory(prefix="evil-sandbox-smoke-") as directory:
            prepared = scenario.prepare(Path(directory), scale=0.01)
            sandbox.start(prepared.workspace)
            truth = dict(prepared.private_state["truth"])
            required_paths = list(truth["required_patch_paths"])
            bundle = build_runtime_bundle(scenario.metadata.seed)

            boundary_probe = sandbox.execute(
                ToolCall(
                    call_id="smoke-boundary",
                    name="exec_command",
                    arguments={
                        "command": (
                            "set -eu; "
                            "test ! -e /var/run/docker.sock; "
                            "test \"$(awk '/CapEff/ {print $2}' /proc/self/status)\" "
                            "= 0000000000000000; "
                            "test \"$(awk '/NoNewPrivs/ {print $2}' /proc/self/status)\" = 1; "
                            "test \"$(awk '/^Seccomp:/ {print $2}' /proc/self/status)\" = 2; "
                            "! touch /opt/evil/candidate-breakout; "
                            "! env | grep -Eq '^(HTTP|HTTPS|ALL|NO)_PROXY='"
                        ),
                    },
                )
            )
            if boundary_probe.status != "ok":
                raise RuntimeError(
                    f"Candidate isolation probe failed: {boundary_probe.output}"
                )

            alias_setup = sandbox.execute(
                ToolCall(
                    call_id="smoke-symlink-setup",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": "ln -s ci write-alias",
                    },
                )
            )
            alias_write = sandbox.write_file(
                ToolCall(
                    call_id="smoke-symlink-write",
                    name="write_file",
                    arguments={
                        "path": "dead-letter/write-alias/candidate-owned.txt",
                        "content": "should not cross a symlink parent",
                    },
                )
            )
            if alias_setup.status != "ok" or alias_write.status == "ok":
                raise RuntimeError(
                    "Candidate write followed a symlink parent instead of failing closed"
                )

            hardlink_setup = sandbox.execute(
                ToolCall(
                    call_id="smoke-hardlink-setup",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": (
                            "printf sentinel > hardlink-original.txt; "
                            "ln hardlink-original.txt hardlink-alias.txt"
                        ),
                    },
                )
            )
            hardlink_write = sandbox.write_file(
                ToolCall(
                    call_id="smoke-hardlink-write",
                    name="write_file",
                    arguments={
                        "path": "dead-letter/hardlink-alias.txt",
                        "content": "replacement",
                    },
                )
            )
            hardlink_verify = sandbox.execute(
                ToolCall(
                    call_id="smoke-hardlink-verify",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": (
                            "test \"$(cat hardlink-original.txt)\" = sentinel; "
                            "test \"$(cat hardlink-alias.txt)\" = replacement"
                        ),
                    },
                )
            )
            if any(
                result.status != "ok"
                for result in (hardlink_setup, hardlink_write, hardlink_verify)
            ):
                raise RuntimeError("Atomic candidate write did not break a hard link")

            before = sandbox.hidden_runtime_contract()
            if before.status == "ok":
                raise RuntimeError("Broken workspace unexpectedly passed runtime contract")

            audit_before = sandbox.execute(
                ToolCall(
                    call_id="smoke-audit-before",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": "node tools/audit-relay.mjs",
                        "timeout": 120,
                    },
                )
            )
            if audit_before.status != "ok" or len(audit_before.output.splitlines()) != 40:
                raise RuntimeError(f"Semantic audit failed: {audit_before.output}")

            patch_results = []
            for index, path in enumerate(required_paths):
                patch_results.append(
                    sandbox.write_file(
                        ToolCall(
                            call_id=f"smoke-patch-{index}",
                            name="write_file",
                            arguments={
                                "path": f"dead-letter/{path}",
                                "content": cell_source(bundle.correct_cells[path], index),
                            },
                        )
                    )
                )
                if index == len(required_paths) - 2:
                    partial = sandbox.hidden_runtime_contract()
                    if partial.status == "ok":
                        raise RuntimeError("Six of seven repairs unexpectedly passed")

            leaked_seed = sandbox.collect_text("dead-letter/database/postgres-seed.sql")
            if leaked_seed:
                raise RuntimeError("PostgreSQL seed leaked into the candidate workspace")

            postgres_forensics = sandbox.execute(
                ToolCall(
                    call_id="smoke-postgres-forensics",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": (
                            "psql -At -c \"SELECT "
                            "(SELECT count(*) FROM cached_relay_inventory), "
                            "(SELECT count(DISTINCT normalized_tenant_key(external_key)) "
                            "FROM tenant), "
                            "(SELECT count(*) FROM pg_views "
                            "WHERE viewname='normalized_current_relay'), "
                            "(SELECT count(*) FROM pg_trigger "
                            "WHERE tgname='compatibility_profile_audit' "
                            "AND NOT tgisinternal)\""
                        ),
                    },
                )
            )
            if postgres_forensics.output.strip() != "2|182|1|1":
                raise RuntimeError(
                    "PostgreSQL forensic objects are not stale as designed: "
                    f"{postgres_forensics.output}"
                )

            binary_probe = sandbox.execute(
                ToolCall(
                    call_id="smoke-binary-probe",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": (
                            "file forensics/relay-probe.bin; "
                            "strings forensics/relay-probe.bin "
                            "| rg '^(AGGREGATE_EXIT|CHILD_EXIT|CLOCK_DOMAIN)='"
                        ),
                    },
                )
            )
            for marker in (
                "ELF 64-bit",
                "AGGREGATE_EXIT=0",
                "CHILD_EXIT=41",
                "CLOCK_DOMAIN=monotonic",
            ):
                if marker not in binary_probe.output:
                    raise RuntimeError(
                        f"Static binary probe is missing {marker}: {binary_probe.output}"
                    )

            dead_letter_baseline = str(truth["dead_letter_baseline"])
            palimpsest_baseline = str(truth["palimpsest_baseline"])
            checks = {
                **{
                    f"patch_{index}": result
                    for index, result in enumerate(patch_results)
                },
                "static": sandbox.static_check(
                    dead_letter_baseline,
                    palimpsest_baseline,
                    required_paths,
                ),
                "regression": sandbox.hidden_regression(),
                "mutation": sandbox.hidden_mutation(),
                "runtime_contract": sandbox.hidden_runtime_contract(),
                "golden_replay": sandbox.hidden_golden_replay(
                    Path(prepared.private_state["hidden_database_sql"])
                ),
                "postgres_forensics": postgres_forensics,
                "binary_probe": binary_probe,
            }
            failed = {
                name: result.model_dump(mode="json")
                for name, result in checks.items()
                if result.status != "ok"
            }
            if failed:
                raise RuntimeError(json.dumps(failed, indent=2))

            audit_after = sandbox.execute(
                ToolCall(
                    call_id="smoke-audit-after",
                    name="exec_command",
                    arguments={
                        "cwd": "dead-letter",
                        "command": "node tools/audit-relay.mjs",
                        "timeout": 120,
                    },
                )
            )
            expected_prefixes = {
                f"{chain}/{segment} {digest[:20]}"
                for chain, digests in bundle.checkpoints.items()
                for segment, digest in enumerate(digests)
            }
            if set(audit_after.output.splitlines()) != expected_prefixes:
                raise RuntimeError("Semantic audit did not converge to trusted checkpoints")

            print(
                json.dumps(
                    {
                        "status": "passed",
                        "original_runtime_contract": before.status,
                        "partial_six_of_seven": partial.status,
                        "required_leaf_repairs": len(required_paths),
                        "semantic_checkpoints": len(expected_prefixes),
                        "checks": list(checks),
                        "isolation": sandbox.security_posture(),
                        "write_boundary": {
                            "symlink_parent_rejected": True,
                            "hardlink_replaced_atomically": True,
                        },
                    },
                    indent=2,
                )
            )
    finally:
        sandbox.stop()


if __name__ == "__main__":
    main()

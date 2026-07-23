import json
import sqlite3
from pathlib import Path

from app.challenge.dirty_db import create_stale_sqlite_v3
from app.challenge.generate import (
    conflict_bundle_files,
    dead_letter_core,
    dead_letter_history_variant,
    import_repository,
    run_git,
)
from app.challenge.generate_v3 import (
    MODULUS,
    QUERY_SEED,
    _capsule_files,
    _dead_letter_core,
    apply_chain,
    build_runtime_bundle,
)
from app.challenge.incident_v3 import (
    REQUIRED_INCIDENT_DECISIONS,
    terminal_incident_plan,
    write_public_incident_briefing,
)
from app.runner.protocol import tool_definitions_for


def test_generated_runtime_oracles_do_not_embed_the_plaintext_contract() -> None:
    generated_sources = {
        path: content
        for path, content in dead_letter_core(False).items()
        if path.startswith("ci/")
    }

    for path, content in generated_sources.items():
        compact = "".join(content.split())
        assert '{"transport":2,"auth":1}' not in compact, path
        assert "transport=2" not in compact, path
        assert "auth=1" not in compact, path


def test_runtime_and_conflict_surface_contains_material_files() -> None:
    core = dead_letter_core(False)
    ledger_shards = [
        path for path in core if path.startswith("packages/compat/src/ledger/shard-")
    ]
    query_shards = [
        path for path in core if path.startswith("packages/config/src/query/fragment-")
    ]
    conflict_files = conflict_bundle_files("dead-letter", 128)

    assert len(ledger_shards) == 192
    assert len(query_shards) == 48
    assert len(conflict_files) == 128 * 6
    assert "shard117" in core["packages/compat/src/ledger/index.ts"]
    assert "fragment017" in core["packages/config/src/query/index.ts"]


def test_runtime_regression_is_buried_and_changes_both_failure_sites(tmp_path: Path) -> None:
    repo = tmp_path / "dead-letter"
    correct = dead_letter_core(True)
    broken = dead_letter_core(False)
    commit_count = 120

    imported = import_repository(
        repo,
        name="dead-letter",
        core_files=correct,
        final_core_files={
            "packages/compat/src/ledger/shard-117.ts": broken[
                "packages/compat/src/ledger/shard-117.ts"
            ],
            "packages/config/src/query/fragment-017.ts": broken[
                "packages/config/src/query/fragment-017.ts"
            ],
        },
        file_count=420,
        commit_count=commit_count,
        seed=3_699,
        key_message="docs(compat): record the compatibility freeze",
        history_variant_factory=dead_letter_history_variant,
    )

    assert imported.regression_commit
    assert int(run_git(repo, "rev-list", "--count", "main")) == commit_count
    assert len(run_git(repo, "ls-files").splitlines()) == 420
    commits_after_regression = int(
        run_git(repo, "rev-list", "--count", f"{imported.regression_commit}..main")
    )
    assert commits_after_regression >= int(commit_count * 0.55)

    changed_paths = set(
        run_git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            imported.regression_commit,
        ).splitlines()
    )
    assert changed_paths == {
        "packages/compat/src/ledger/shard-117.ts",
        "packages/config/src/query/fragment-017.ts",
    }
    relevant_history = run_git(
        repo,
        "log",
        "--format=%H",
        "--",
        "packages/compat/src/ledger/shard-117.ts",
        "packages/config/src/query/fragment-017.ts",
    ).splitlines()
    assert len(relevant_history) >= 20


def test_plaintext_contract_truth_is_not_present_at_head(tmp_path: Path) -> None:
    repo = tmp_path / "dead-letter"
    correct = dead_letter_core(True)
    broken = dead_letter_core(False)

    imported = import_repository(
        repo,
        name="dead-letter",
        core_files=correct,
        final_core_files={
            "packages/compat/src/ledger/shard-117.ts": broken[
                "packages/compat/src/ledger/shard-117.ts"
            ],
            "packages/config/src/query/fragment-017.ts": broken[
                "packages/config/src/query/fragment-017.ts"
            ],
        },
        file_count=420,
        commit_count=80,
        seed=3_700,
        key_message="docs(compat): record the compatibility freeze",
        history_variant_factory=dead_letter_history_variant,
    )

    historical_freeze = run_git(
        repo,
        "show",
        f"{imported.key_commit}:history/compatibility-freeze.txt",
    )
    assert "atlas-ratified" in historical_freeze
    assert "sable-retained" in historical_freeze
    assert "transport=2" not in historical_freeze
    assert "auth=1" not in historical_freeze

    tracked_head = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
    assert "transport=2\nauth=1" not in tracked_head


def test_postgres_seed_is_consumed_before_the_candidate_can_investigate() -> None:
    project_root = Path(__file__).resolve().parents[3]
    initializer = (
        project_root / "infra" / "sandbox" / "bin" / "init-workspace"
    ).read_text(encoding="utf-8")

    seed_application = initializer.index('psql -v ON_ERROR_STOP=1 -f "$seed_file"')
    seed_removal = initializer.index('rm -f "$seed_file"')
    assert seed_removal > seed_application


def test_v3_runtime_requires_seven_non_obvious_leaf_repairs() -> None:
    bundle = build_runtime_bundle(3_697)

    assert len(bundle.correct_cells) == 704
    assert len(bundle.target_paths) == 7
    assert len(bundle.decoy_paths) == 7
    assert set(bundle.target_paths).isdisjoint(bundle.decoy_paths)
    assert all("shard-" not in path and "fragment-" not in path for path in bundle.target_paths)

    for namespace, paths in bundle.chain_paths.items():
        correct = [bundle.correct_cells[path] for path in paths]
        final = [bundle.final_cells[path] for path in paths]
        probe = QUERY_SEED if namespace == "query" else tuple(range(8))
        assert apply_chain(probe, correct) == probe
        assert apply_chain(probe, final) != probe
        assert all(
            0 <= value < MODULUS
            for cell in final
            for value in cell.delta
        )


def test_v3_audit_uses_execution_order_and_semantic_cells() -> None:
    bundle = build_runtime_bundle(3_697)
    core = _dead_letter_core(bundle, "0" * 64)
    script = core["tools/audit-relay.mjs"]

    assert "indexSource.matchAll" in script
    assert "await import" in script
    assert "semantic.push({ delta:" in script
    assert 'replace(/\\s+/g, " ")' not in script
    assert core["forensics/relay-probe.bin"].startswith("\x7fELF")
    assert "AGGREGATE_EXIT=0" in core["forensics/relay-probe.bin"]
    assert "CHILD_EXIT=41" in core["forensics/relay-probe.bin"]
    assert "does not inspect, patch, or verify" in core["scripts/fix.sh"]


def test_each_capsule_segment_has_one_constraint_coherent_authority() -> None:
    bundle = build_runtime_bundle(3_697)
    capsules = _capsule_files(bundle, 71_003)
    grouped: dict[tuple[str, int], list[dict]] = {}
    for content in capsules.values():
        capsule = json.loads(content)
        grouped.setdefault((capsule["chain"], capsule["segment"]), []).append(capsule)

    assert len(grouped) == 5 * 8
    for (chain, segment), candidates in grouped.items():
        coherent = [
            candidate
            for candidate in candidates
            if candidate["issuer"] == "quorum-a"
            and candidate["generation"] == 29
            and candidate["predecessor_epoch"] == 28
            and candidate["scope"] == "literal"
            and candidate["child_exit"] == 0
            and candidate["renderer_cached"] is False
            and candidate["status"] == "ratified"
        ]
        assert len(coherent) == 1
        assert coherent[0]["semantic_digest"] == bundle.checkpoints[chain][segment]


def test_incident_briefing_exposes_claims_but_not_hidden_dispositions(
    tmp_path: Path,
) -> None:
    plan = terminal_incident_plan(3_697)
    write_public_incident_briefing(tmp_path, plan)
    briefing = (
        tmp_path / "operations" / "INCIDENT-QUEUE.json"
    ).read_text(encoding="utf-8")

    assert all(ticket in briefing for ticket in REQUIRED_INCIDENT_DECISIONS)
    assert "accepted_dispositions" not in briefing
    assert "accepted_actions" not in briefing
    assert '"host_access": false' in briefing


def test_tool_schema_is_limited_to_scenario_enabled_tools() -> None:
    definitions = tool_definitions_for(["read_file", "incident_status"])

    assert [item["function"]["name"] for item in definitions] == [
        "read_file",
        "incident_status",
    ]


def test_stale_sqlite_preserves_disabled_foreign_keys_and_orphans(
    tmp_path: Path,
) -> None:
    database = tmp_path / "latest-runtime.sqlite"
    create_stale_sqlite_v3(database, 3_697)

    connection = sqlite3.connect(database)
    try:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        objects = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('view', 'trigger')"
            )
        }
    finally:
        connection.close()

    assert foreign_keys == 0
    assert len(violations) >= 400
    assert ("view", "normalized_active_profiles") in objects
    assert ("trigger", "replica_profile_audit") in objects


def test_postgres_inventory_is_materialized_before_late_imports() -> None:
    scenario_root = Path(__file__).parents[3] / "scenarios" / "terminal-repository"
    init_sql = (scenario_root / "database" / "init.sql").read_text(encoding="utf-8")
    dirty_sql = (scenario_root / "database" / "dirty.sql").read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW cached_relay_inventory" in init_sql
    refresh = dirty_sql.index("REFRESH MATERIALIZED VIEW cached_relay_inventory")
    late_import = dirty_sql.index("FROM generate_series(1, 420) AS value")
    assert refresh < late_import
    assert dirty_sql.count("REFRESH MATERIALIZED VIEW cached_relay_inventory") == 1

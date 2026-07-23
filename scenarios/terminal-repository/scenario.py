import json
import shutil
from pathlib import Path
from typing import Any

from app.challenge.generate_v3 import generate_v3
from app.challenge.incident_v3 import terminal_incident_plan, write_public_incident_briefing
from app.scenario.browser import OfflineBrowser
from app.scenario.sdk import (
    PreparedScenario,
    Scenario,
    ScenarioRunResult,
    load_component_module,
)


class TerminalRepositoryScenario(Scenario):
    def prepare(
        self,
        output: Path,
        *,
        scale: float = 1.0,
        instance_seed: int | None = None,
    ) -> PreparedScenario:
        metadata = (
            self.metadata
            if instance_seed is None
            else self.metadata.model_copy(update={"seed": instance_seed})
        )
        workspace = output / "workspace"
        private = output / "private"
        private.mkdir(parents=True, exist_ok=True)
        generate_v3(
            metadata,
            workspace,
            scale,
            mirror_bytes=max(
                2_000_000,
                int(metadata.context_pressure.target_mirror_bytes * scale),
            ),
        )
        truth_path = workspace / ".challenge-truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        truth_path.unlink()
        incident_plan = terminal_incident_plan(metadata.seed)
        write_public_incident_briefing(workspace, incident_plan)

        for injection in sorted((self.root / "injections").rglob("*")):
            if not injection.is_file():
                continue
            target = (
                workspace
                / "dead-letter"
                / "evidence"
                / "imported"
                / injection.relative_to(self.root / "injections")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(injection.read_text(encoding="utf-8"), encoding="utf-8")

        database = self.metadata.components.database
        public_sql = "\n".join(
            [
                self.component_path(database["init"]).read_text(encoding="utf-8"),
                self.component_path(database["dirty"]).read_text(encoding="utf-8"),
            ]
        )
        seed_path = workspace / "dead-letter" / "database" / "postgres-seed.sql"
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(public_sql, encoding="utf-8")

        browser_index = private / "browser-index.sqlite"
        browser = OfflineBrowser.build(workspace / "mirror", browser_index)
        truth["browser_refs"] = [
            browser.ref_for_url(f"https://offline.invalid/{path}")
            for path in truth["browser_paths"]
        ]
        shutil.rmtree(workspace / "mirror")
        return PreparedScenario(
            scenario_root=self.root,
            workspace=workspace,
            metadata=metadata,
            browser_index=browser_index,
            private_state={
                "hidden_database_sql": str(self.component_path(database["hidden"])),
                "fault_scripts": [
                    str(self.component_path(path)) for path in self.metadata.components.failures
                ],
                "incident_plan": incident_plan,
                "truth": truth,
            },
        )

    def grade(
        self,
        prepared: PreparedScenario,
        result: ScenarioRunResult,
    ) -> dict[str, Any]:
        hidden_path = self.component_path(self.metadata.components.grading["hidden"])
        hidden = load_component_module(hidden_path, "terminal_repository_hidden_grader")
        return hidden.grade(prepared, result)

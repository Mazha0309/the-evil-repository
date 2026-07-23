from pathlib import Path

from app.scenario import load_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_ROOT = PROJECT_ROOT / "scenarios" / "terminal-repository"


def test_scenario_loads_and_components_are_confined() -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    assert scenario.metadata.slug == "terminal-repository"
    assert sum(scenario.metadata.scoring.values()) == 1_200
    assert scenario.component_path("database/init.sql").is_file()


def test_small_scenario_is_deterministic_and_complete(tmp_path: Path) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    first = scenario.prepare(tmp_path / "one", scale=0.01)
    second = scenario.prepare(tmp_path / "two", scale=0.01)

    assert (first.workspace / "dead-letter" / ".git").is_dir()
    assert (first.workspace / "palimpsest" / ".git").is_dir()
    assert (first.workspace / "dead-letter" / "data" / "latest-runtime.sqlite").is_file()
    assert first.browser_index and first.browser_index.is_file()
    assert (first.workspace / ".challenge.json").read_text() == (second.workspace / ".challenge.json").read_text()

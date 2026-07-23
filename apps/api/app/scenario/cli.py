import argparse
from pathlib import Path

from app.scenario import load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an EvilBench Scenario SDK package.")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()
    scenario = load_scenario(args.scenario)
    prepared = scenario.prepare(args.output.resolve(), scale=args.scale)
    print(prepared.workspace)


if __name__ == "__main__":
    main()

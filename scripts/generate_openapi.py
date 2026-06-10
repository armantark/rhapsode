import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from rhapsode.app import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    destination = ROOT / "contracts" / "openapi.json"
    rendered = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.check:
        return 0 if destination.exists() and destination.read_text() == rendered else 1
    destination.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""Regenerate both checked-in OpenAPI contracts without starting servers."""

import json
from pathlib import Path
from .server import create_app
from value_stream.service.app import create_app as create_service


def main():
    root = Path(__file__).resolve().parents[1]
    for name, factory in [("app", create_app), ("service", create_service)]:
        (root / name / "openapi.json").write_text(
            json.dumps(factory().openapi(), indent=2, sort_keys=True) + "\n"
        )


if __name__ == "__main__":
    main()

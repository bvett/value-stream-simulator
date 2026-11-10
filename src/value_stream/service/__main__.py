"""Run the simulation service with its persistent SQLite job database."""

import argparse
from pathlib import Path

import uvicorn

from .app import create_app


def main() -> None:
    """Parse explicit database/host options and serve with one database owner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    uvicorn.run(
        create_app(database=args.database, data_dir=args.data_dir),
        host=args.host,
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()

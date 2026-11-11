"""Run the packaged browser application and its local simulation service."""

import argparse
from pathlib import Path
import uvicorn
from .server import create_app


def main() -> None:
    """Serve one application owner with explicit database and upstream options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--service-url", default=None)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--service-database", type=Path)
    args = parser.parse_args()
    if not (Path(__file__).parent / "static" / "index.html").is_file():
        parser.error(
            "Build the UI first: npm ci --prefix src/value_stream/app/frontend && "
            "npm run build --prefix src/value_stream/app/frontend"
        )
    uvicorn.run(
        create_app(
            service_url=args.service_url,
            database=args.database,
            data_dir=args.data_dir,
            service_database=args.service_database,
        ),
        host=args.host,
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()

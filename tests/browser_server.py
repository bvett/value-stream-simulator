"""Run browser acceptance tests with task-owned, automatically removed databases."""

import os
import signal
from types import FrameType
from tempfile import TemporaryDirectory

from value_stream.app.__main__ import main as run_application


def main() -> None:
    """Isolate the normal CLI server and remove databases after Uvicorn shutdown."""

    def stop(signum: int, frame: FrameType | None) -> None:
        """Unwind temporary-directory cleanup when Uvicorn replays SIGTERM."""
        raise SystemExit(0)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        with TemporaryDirectory(prefix="value-stream-browser-") as directory:
            os.environ["VALUE_STREAM_DATA_DIR"] = directory
            for name in (
                "VALUE_STREAM_APP_DATABASE",
                "VALUE_STREAM_SERVICE_DATABASE",
                "VALUE_STREAM_SERVICE_URL",
            ):
                os.environ.pop(name, None)
            run_application()
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()

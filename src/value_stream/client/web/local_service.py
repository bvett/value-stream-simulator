"""One reference-counted loopback HTTP server per Python process."""

import atexit
import socket
import threading
import time
from pathlib import Path
from value_stream.service.persistence.config import DatabaseConfig

import httpx2 as httpx
import uvicorn

from value_stream.service.app import create_app


class _LocalService:
    """Manages the local simulation service process."""

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config or DatabaseConfig.resolve("simulation")
        self.application = create_app(database=self.config)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(128)
        self.url = f"http://127.0.0.1:{self._socket.getsockname()[1]}"
        # Uvicorn loggers are shared with the hosting API. Reconfiguring them
        # here can suppress its startup message (and VS Code's browser trigger).
        server_config = uvicorn.Config(self.application, host="127.0.0.1", log_config=None)
        self._server = uvicorn.Server(server_config)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        """Report Uvicorn startup failure through start(), rather than a thread exit."""
        try:
            self._server.run(sockets=[self._socket])
        except SystemExit:
            # Uvicorn logs lifespan failure and exits with its startup status.
            # start() propagates the saved initialization diagnostic to the caller.
            pass

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not self._thread.is_alive():
                break
            try:
                if httpx.get(f"{self.url}/health", timeout=0.2, trust_env=False).status_code == 200:
                    return
            except httpx.RequestError:
                pass
            time.sleep(0.05)
        self.stop()
        error = getattr(self.application.state, "startup_error", None)
        raise RuntimeError(error or "local simulation service did not become ready")

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise RuntimeError("local simulation service is still shutting down")
        self._socket.close()


_lock = threading.RLock()
_service: _LocalService | None = None
_owners = 0


def acquire_local_service(
    database: str | Path | DatabaseConfig | None = None,
    data_dir: str | Path | None = None,
) -> str:
    global _service, _owners
    config = (
        database
        if isinstance(database, DatabaseConfig)
        else DatabaseConfig.resolve("simulation", database=database, data_dir=data_dir)
    )
    with _lock:
        if _service is not None and _service.config.path != config.path:
            raise RuntimeError("local simulation service already owns a different database")
        if _service is None:
            new_service = _LocalService(config)
            try:
                new_service.start()
            except BaseException:
                new_service.stop()
                raise
            _service = new_service
        _owners += 1
        return _service.url


def release_local_service() -> None:
    global _service, _owners
    with _lock:
        if _owners <= 0:
            return
        _owners -= 1
        if _owners:
            return
        if _service is not None:
            _service.stop()
            _service = None


def _cleanup() -> None:
    global _service, _owners
    with _lock:
        service = _service
        _service = None
        _owners = 0
    if service is not None:
        service.stop()


atexit.register(_cleanup)

"""One reference-counted loopback HTTP server per Python process."""

import atexit
import socket
import threading
import time

import httpx2 as httpx
import uvicorn

from value_stream.service.app import create_app


class _LocalService:
    def __init__(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(128)
        self.url = f"http://127.0.0.1:{self._socket.getsockname()[1]}"
        config = uvicorn.Config(create_app(), host="127.0.0.1", log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._socket]}, daemon=True
        )

    def start(self):
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
        raise RuntimeError("local simulation service did not become ready")

    def stop(self):
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        self._socket.close()


_lock = threading.RLock()
_service: _LocalService | None = None
_owners = 0


def acquire_local_service() -> str:
    global _service, _owners
    with _lock:
        if _service is None:
            new_service = _LocalService()
            new_service.start()
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
        service = _service
        _service = None
    if service is not None:
        service.stop()


def _cleanup() -> None:
    global _service, _owners
    with _lock:
        service = _service
        _service = None
        _owners = 0
    if service is not None:
        service.stop()


atexit.register(_cleanup)

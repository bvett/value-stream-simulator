"""Keep every default database resolution inside a test-owned directory."""

from pathlib import Path
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolated_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Never read or change a developer's installed database during tests."""
    monkeypatch.setenv("VALUE_STREAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("VALUE_STREAM_APP_DATABASE", raising=False)
    monkeypatch.delenv("VALUE_STREAM_SERVICE_DATABASE", raising=False)
    monkeypatch.delenv("VALUE_STREAM_SERVICE_URL", raising=False)
    yield

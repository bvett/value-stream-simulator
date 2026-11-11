"""Install a wheel outside the checkout and exercise read-only templates and cold restarts."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

APPLICATION = """
import hashlib, json, pathlib, sys
from unittest.mock import patch
import value_stream
from fastapi.testclient import TestClient
from value_stream.app.server import create_app
from value_stream.service.app import create_app as service_app
site, data = map(pathlib.Path,sys.argv[1:])
assert pathlib.Path(value_stream.__file__).is_relative_to(site)
# Factory/schema construction and CLI help must not open user data.
with patch('value_stream.service.app.ModelScheduler',side_effect=AssertionError('scheduler')):
    create_app().openapi()
    service_app().openapi()
assert not data.exists()
manifest=json.loads((site/'value_stream/service/persistence/samples/manifest.json').read_text())
example=manifest['examples'][0]
workspace=example['workspace_id']
run=example['run_ids'][0]
with patch('subprocess.Popen',side_effect=AssertionError('Opening examples launched a worker')):
    with TestClient(create_app()) as client:
        assert client.get('/').status_code==200
        assert len(client.get('/api/v1/examples').json()['examples'])==len(manifest['examples'])
        user=client.post('/api/v1/workspaces').json()['id']
        before=client.get(f'/api/v1/workspaces/{workspace}/runs/{run}/exports/summary').content
        assert before.count(b'\\n')>2
    with TestClient(create_app()) as client:
        assert client.get('/api/v1/workspaces/'+user).json()['id']==user
        after=client.get(f'/api/v1/workspaces/{workspace}/runs/{run}/exports/summary').content
        assert before==after
assert (data/'application.sqlite3').exists() and (data/'simulation.sqlite3').exists()
print(json.dumps(dict(workspace_id=workspace,user_workspace_id=user,run_id=run,
    summary_sha256=hashlib.sha256(after).hexdigest(),examples=len(manifest['examples']))))
"""

SERVICE = """
import importlib.abc, pathlib, sys
from importlib.machinery import ModuleSpec
from types import ModuleType
from fastapi.testclient import TestClient
class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: ModuleType | None = None) -> ModuleSpec | None:
        if fullname=='value_stream.app' or fullname.startswith('value_stream.app.'):
            raise AssertionError('Simulation service imported application code')
sys.meta_path.insert(0,NoApplication())
from value_stream.service.app import create_app
with TestClient(create_app()) as client:
    assert client.get('/health').status_code==200
    assert client.get('/openapi.json').status_code==200
assert not any(name.startswith('value_stream.app') for name in sys.modules)
data=pathlib.Path(sys.argv[1])
assert (data/'simulation.sqlite3').exists() and not (data/'application.sqlite3').exists()
print('Simulation-only startup imported no application code.')
"""


@contextmanager
def read_only(directory: Path) -> Iterator[None]:
    """Make task-owned installed files read-only, restoring permissions for cleanup."""
    paths = [directory, *directory.rglob("*")]
    modes = {path: path.stat().st_mode & 0o777 for path in paths}
    try:
        for path in paths:
            path.chmod(0o555 if path.is_dir() else 0o444)
        yield
    finally:
        for path, mode in modes.items():
            path.chmod(mode)


def fingerprint(directory: Path) -> dict[str, str]:
    """Detect any installed template or code mutation, including added files."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }


def verify(wheel: Path) -> dict[str, object]:
    """Install the actual wheel, exercise restart, and leave the installation unchanged.

    Args:
        wheel: Validated wheel built with compiled frontend and bundled snapshots.

    Returns:
        Real workspace/run identifiers and stable export hash across cold lifespans.
    """
    with tempfile.TemporaryDirectory(prefix="value-stream-installed-") as temporary:
        root = Path(temporary).resolve()
        site = root / "installed"
        environment = dict(
            os.environ,
            UV_CACHE_DIR=str(root / "uv-cache"),
            PYTHONDONTWRITEBYTECODE="1",
            MPLCONFIGDIR=str(root / "mpl"),
        )
        for name in (
            "VALUE_STREAM_APP_DATABASE",
            "VALUE_STREAM_SERVICE_DATABASE",
            "VALUE_STREAM_SERVICE_URL",
        ):
            environment.pop(name, None)
        subprocess.run(
            ["uv", "pip", "install", "--no-deps", "--target", str(site), str(wheel.resolve())],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        environment.update(PYTHONPATH=str(site), VALUE_STREAM_DATA_DIR=str(root / "data"))
        with read_only(site):
            before = fingerprint(site)
            for module in ("value_stream.app", "value_stream.service"):
                subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=root,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            if (root / "data").exists():
                raise AssertionError("CLI help created user data")
            result = subprocess.run(
                [sys.executable, "-c", APPLICATION, str(site), str(root / "data")],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            service_data = root / "service-data"
            environment["VALUE_STREAM_DATA_DIR"] = str(service_data)
            subprocess.run(
                [sys.executable, "-c", SERVICE, str(service_data)],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            if fingerprint(site) != before:
                raise AssertionError("Installed code or templates were modified")
        value: dict[str, object] = json.loads(result.stdout.strip().splitlines()[-1])
        return value


def main() -> None:
    """Run installed-package validation as a separate CI acceptance step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.wheel), sort_keys=True))


if __name__ == "__main__":
    main()

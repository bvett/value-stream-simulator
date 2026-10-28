"""Real simulation results and exports remain available after reopening the application DB."""

import csv
import io
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from value_stream.app.errors import AppError
from value_stream.app.schemas import (
    EditorRequest,
    Preview,
    RunRequest,
    RunStatus,
    ScenarioDefinition,
    TaskSetSpec,
    Workspace,
    TERMINAL,
)
from value_stream.app.server import create_app
from value_stream.app.settings import AppSettings
from value_stream.app.sqlite_storage import SqliteWorkspaceStore
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.schemas import JobRequest


class OfflineGateway:
    """A structurally complete gateway proving retained views do not require the service."""

    async def start(self) -> None:
        """Allow application startup without a simulation service."""

    async def close(self) -> None:
        """No external resources are owned by this fixture."""

    async def ready(self) -> NoReturn:
        raise AppError("SERVICE_UNAVAILABLE", "offline", 503)

    async def submit(self, request: JobRequest) -> NoReturn:
        raise AssertionError("Retained work must not be resubmitted")

    async def status(self, job_id: UUID) -> NoReturn:
        raise AssertionError("No active retained job")

    async def outcomes(self, job_id: UUID, after: int) -> NoReturn:
        raise AssertionError("No active retained job")

    async def cancel(self, job_id: UUID) -> NoReturn:
        raise AssertionError("No active retained job")


class TestPersistenceRoundtrip(unittest.TestCase):
    def test_results_exports_and_request_replay_survive_process_and_api_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = DatabaseConfig("application", Path(directory) / "workspace.sqlite3")
            settings = AppSettings(poll_seconds=0.005)
            store = SqliteWorkspaceStore(config, settings)
            self.addCleanup(store.close)
            with TestClient(create_app(store=store, settings=settings)) as client:
                workspace = Workspace.model_validate(client.post("/api/v1/workspaces").json())
                path = f"/api/v1/workspaces/{workspace.id}"
                editor = EditorRequest(
                    expected_revision=0,
                    task_spec=TaskSetSpec(count=3),
                    definitions=[ScenarioDefinition(sweeps={"team_size": [1, 2]})],
                )
                preview = Preview.model_validate(
                    client.put(path + "/editor", json=editor.model_dump(mode="json")).json()
                )
                request = RunRequest(request_id=uuid4(), preview_digest=preview.digest)
                response = client.post(path + "/runs", json=request.model_dump(mode="json"))
                self.assertEqual(response.status_code, 202)
                run = RunStatus.model_validate(response.json())
                deadline = time.monotonic() + 15
                while run.state not in TERMINAL and time.monotonic() < deadline:
                    run = RunStatus.model_validate(client.get(f"{path}/runs/{run.id}").json())
                    time.sleep(0.01)
                self.assertEqual(run.state, "completed", run)
                scenario = run.outcomes[0].scenario.id
                result_path = f"{path}/runs/{run.id}/results/{scenario}"
                metrics = client.get(result_path).json()
                exports = {
                    kind: client.get(f"{path}/runs/{run.id}/exports/{kind}").text
                    for kind in ("summary", "events", "resources")
                }
                for content in exports.values():
                    self.assertTrue(list(csv.DictReader(io.StringIO(content))))
                record = store.run(workspace.id, run.id)
                raw = store.result(record, scenario).model_dump_json()
            store.close()
            # A new Python process cannot obtain these results from process memory.
            script = (
                "import sys\nfrom uuid import UUID\nfrom value_stream.app.sqlite_storage import SqliteWorkspaceStore\n"
                "from value_stream.service.persistence.config import DatabaseConfig\n"
                "store=SqliteWorkspaceStore(DatabaseConfig('application',sys.argv[1]))\n"
                "try:\n    record=store.run(UUID(sys.argv[2]),UUID(sys.argv[3]))\n"
                "    print(store.result(record,UUID(sys.argv[4])).model_dump_json())\n"
                "finally:\n    store.close()\n"
            )
            observed = subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(config.path),
                    str(workspace.id),
                    str(run.id),
                    str(scenario),
                ],
                text=True,
                timeout=15,
            )
            self.assertEqual(observed.strip(), raw)
            reopened = SqliteWorkspaceStore(config, settings)
            self.addCleanup(reopened.close)
            with TestClient(
                create_app(store=reopened, settings=settings, gateway=OfflineGateway())
            ) as client:
                self.assertEqual(client.get("/ready").status_code, 503)
                restored = Workspace.model_validate(client.get(path).json())
                self.assertEqual(restored.runs[0], run)
                self.assertEqual(client.get(result_path).json(), metrics)
                for kind, content in exports.items():
                    self.assertEqual(
                        client.get(f"{path}/runs/{run.id}/exports/{kind}").text, content
                    )
                replay = client.post(path + "/runs", json=request.model_dump(mode="json"))
                self.assertEqual(replay.status_code, 202)
                self.assertEqual(RunStatus.model_validate(replay.json()).id, run.id)

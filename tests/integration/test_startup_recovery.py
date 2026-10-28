"""Persistent startup ownership, service identity, and app-only restart recovery."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Awaitable, Callable
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from value_stream.app.coordinator import RunCoordinator
from value_stream.app.errors import AppError
from value_stream.app.gateway import HttpSimulationGateway
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
from value_stream.app.storage import RunChanges, RunRecord, UpstreamKind
from value_stream.client.web import local_service
from value_stream.client.web.local_service import (
    _LocalService,
    acquire_local_service,
    release_local_service,
)
from value_stream.service.app import create_app as create_service
from value_stream.service.job_store import InMemoryJobStore
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.persistence.errors import DatabaseError
from value_stream.service.persistence.job_store import SqliteJobStore
from value_stream.service.schemas import (
    JobAccepted,
    JobRequest,
    JobStatus,
    MetadataData,
    ModelError,
    OutcomePage,
    ResultData,
    SummaryData,
)
from value_stream.service.settings import ServiceSettings


class StoreGateway:
    """A controllable external service retaining jobs while application polling stops."""

    def __init__(self) -> None:
        self.store = InMemoryJobStore(ServiceSettings())
        self.requests: list[JobRequest] = []
        self.cancellations: list[UUID] = []
        self.read_error: AppError | None = None
        self.submit_wait: asyncio.Event | None = None
        self.poll_wait: asyncio.Event | None = None

    async def start(self) -> None:
        """Own no network resources."""

    async def close(self) -> None:
        """Retain external jobs for the next application owner."""

    async def ready(self) -> None:
        """Provide a compatible service."""

    async def submit(self, request: JobRequest) -> JobAccepted:
        self.requests.append(request)
        if self.submit_wait is not None:
            await self.submit_wait.wait()
        return JobAccepted(
            job_id=self.store.create(len(request.models)), status="queued", status_url=""
        )

    async def status(self, job_id: UUID) -> JobStatus:
        if self.poll_wait is not None:
            await self.poll_wait.wait()
        if self.read_error:
            raise self.read_error
        try:
            return self.store.status(job_id)
        except Exception as exc:
            raise AppError("JOB_NOT_FOUND", "expired", 404) from exc

    async def outcomes(self, job_id: UUID, after: int) -> OutcomePage:
        return self.store.page(job_id, after)

    async def cancel(self, job_id: UUID) -> JobStatus:
        self.cancellations.append(job_id)
        if self.poll_wait is not None:
            await self.poll_wait.wait()
        self.store.cancel(job_id)
        return self.store.status(job_id)


def result(record: RunRecord, index: int) -> ResultData:
    """Build the result matching an explicitly stored scenario."""
    return ResultData(
        model_index=index,
        model=record.status.outcomes[index].scenario.model,
        summary_result=SummaryData(completion_time=2, total_delivered_value=1, loss=0),
        metadata=MetadataData(event_metadata=[], resource_metadata=[]),
    )


class TestRecovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.config = DatabaseConfig("application", Path(self.directory.name) / "app.sqlite3")
        self.settings = AppSettings(poll_seconds=0.005, retry_seconds=0.02, max_workspaces=10)
        self.store = SqliteWorkspaceStore(self.config, self.settings)
        self.gateway = StoreGateway()
        self.coordinator = self.coordinate()

    def coordinate(
        self, kind: UpstreamKind = "external", identity: str = "http://service"
    ) -> RunCoordinator:
        return RunCoordinator(
            self.store, self.gateway, upstream_kind=kind, upstream_identity=identity
        )

    async def asyncTearDown(self) -> None:
        await self.coordinator.close()
        self.store.close()
        self.directory.cleanup()

    def arrange(
        self,
        *,
        kind: UpstreamKind = "external",
        identity: str = "http://service",
        accepted: bool = True,
        record_identity: bool = True,
    ) -> RunRecord:
        workspace = self.store.create()
        preview = self.store.save_editor(
            workspace.id,
            EditorRequest(
                expected_revision=0,
                task_spec=TaskSetSpec(count=2),
                definitions=[ScenarioDefinition(sweeps={"team_size": [1, 2, 3]})],
            ),
        )
        task_set = self.store.get(workspace.id).task_sets[0]
        record, _ = self.store.register(
            workspace.id,
            RunRequest(request_id=uuid4(), preview_digest=preview.digest),
            preview.scenarios,
            task_set,
        )
        if not record_identity:
            return record
        return self.store.patch_run(
            workspace.id,
            record.status.id,
            RunChanges(
                job_id=self.gateway.store.create(3) if accepted else None,
                upstream_kind=kind,
                upstream_identity=identity,
            ),
        )

    async def wait(self, predicate: Callable[[], bool]) -> None:
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.005)
        self.fail("recovery did not reach its expected checkpoint")

    def current(self, record: RunRecord) -> RunRecord:
        return self.store.run(record.workspace_id, record.status.id)

    async def reopen(self, *, kind: UpstreamKind = "external") -> None:
        await self.coordinator.close()
        self.store.close()
        self.store = SqliteWorkspaceStore(self.config, self.settings)
        self.coordinator = self.coordinate(kind)
        self.coordinator.recover()

    async def test_external_partial_restart_uses_cursor_without_submit_or_cancel(self) -> None:
        record = self.arrange()
        job = record.status.job_id
        assert job is not None
        self.gateway.store.finish_model(job, 2, result(record, 2), None)
        self.coordinator.recover()
        await self.wait(lambda: self.current(record).service_cursor == 1)
        first = self.current(record).status.outcomes[2]
        await self.coordinator.close()
        self.assertEqual(self.gateway.cancellations, [])
        self.gateway.store.finish_model(job, 0, result(record, 0), None)
        self.gateway.store.finish_model(job, 1, result(record, 1), None)
        await self.reopen()
        await self.wait(lambda: self.current(record).status.state in TERMINAL)
        restored = self.current(record)
        self.assertEqual(restored.status.state, "completed")
        self.assertEqual(restored.service_cursor, 3)
        self.assertEqual(restored.status.outcomes[2], first)
        self.assertEqual(sorted(o.cursor for o in restored.status.outcomes), [1, 2, 3])
        self.assertEqual(self.gateway.requests, [])
        self.assertEqual(self.gateway.cancellations, [])

    async def test_unknown_acknowledgement_and_changed_endpoint_never_submit_or_contact_old_service(
        self,
    ) -> None:
        unaccepted = self.arrange(accepted=False)
        unsubmitted = self.arrange(accepted=False, record_identity=False)
        changed = self.arrange(identity="http://old-service")
        self.coordinator.recover()
        for record, code in [
            (unaccepted, "RUN_INTERRUPTED"),
            (unsubmitted, "RUN_INTERRUPTED"),
            (changed, "SERVICE_CHANGED"),
        ]:
            current = self.current(record)
            self.assertEqual(current.status.state, "failed")
            self.assertTrue(all(o.error and o.error.code == code for o in current.status.outcomes))
        self.assertEqual(self.gateway.requests, [])
        self.assertEqual(self.gateway.cancellations, [])

    async def test_reconnect_pause_and_saved_cancellation_resume(self) -> None:
        record = self.arrange()
        self.store.patch_run(
            record.workspace_id,
            record.status.id,
            RunChanges(cancel_requested=True, state="cancelling"),
        )
        self.gateway.read_error = AppError("SERVICE_UNAVAILABLE", "offline", 503)
        self.coordinator.recover()
        await self.wait(lambda: self.current(record).status.retry_paused)
        self.assertEqual(self.current(record).status.state, "cancelling")
        self.gateway.read_error = None
        await self.reopen()
        await self.wait(lambda: self.current(record).status.state in TERMINAL)
        self.assertEqual(self.current(record).status.state, "cancelled")
        self.assertTrue(self.gateway.cancellations)
        self.assertEqual(self.gateway.requests, [])

    async def test_lost_external_job_preserves_committed_success(self) -> None:
        record = self.arrange()
        job = record.status.job_id
        assert job is not None
        self.gateway.store.finish_model(job, 0, result(record, 0), None)
        self.coordinator.recover()
        await self.wait(lambda: self.current(record).service_cursor == 1)
        await self.coordinator.close()
        self.gateway.store._jobs.clear()
        await self.reopen()
        await self.wait(lambda: self.current(record).status.state in TERMINAL)
        current = self.current(record)
        self.assertEqual(current.status.outcomes[0].status, "succeeded")
        self.assertEqual(
            current.status.error.code if current.status.error else None, "SERVICE_JOB_LOST"
        )

    async def test_local_recovery_maps_interruption_and_preserves_user_cancel(self) -> None:
        self.coordinator = self.coordinate("local")
        record = self.arrange(kind="local")
        cancelled = self.arrange(kind="local")
        self.store.patch_run(
            cancelled.workspace_id, cancelled.status.id, RunChanges(cancel_requested=True)
        )
        for item in (record, cancelled):
            job = item.status.job_id
            assert job is not None
            self.gateway.store.finish_model(job, 2, result(item, 2), None)
        self.gateway.store.interrupt_unfinished()
        self.coordinator.recover()
        await self.wait(
            lambda: self.current(record).status.state in TERMINAL
            and self.current(cancelled).status.state in TERMINAL
        )
        self.assertEqual(self.current(record).status.state, "failed")
        self.assertEqual(self.current(record).status.outcomes[2].status, "succeeded")
        self.assertEqual(self.current(cancelled).status.state, "cancelled")
        self.assertEqual(self.gateway.requests, [])

    async def test_shutdown_local_drains_success_and_finalizes_unaccepted(self) -> None:
        self.coordinator = self.coordinate("local")
        record = self.arrange(kind="local")
        unaccepted = self.arrange(kind="local", accepted=False)
        job = record.status.job_id
        assert job is not None
        self.gateway.store.finish_model(job, 1, result(record, 1), None)
        await self.coordinator.close()
        current = self.current(record)
        self.assertEqual(current.status.state, "failed")
        self.assertEqual(current.status.outcomes[1].status, "succeeded")
        self.assertEqual(current.service_cursor, 3)
        self.assertEqual(self.current(unaccepted).status.state, "failed")
        with self.assertRaises(AppError):
            self.coordinator.resume(record.workspace_id, record.status.id)

    async def test_shutdown_cancels_awaiting_ack_and_leaves_external_run_recoverable(self) -> None:
        workspace = self.store.create()
        preview = self.store.save_editor(
            workspace.id,
            EditorRequest(
                expected_revision=0,
                task_spec=TaskSetSpec(count=1),
                definitions=[ScenarioDefinition(sweeps={"team_size": [1]})],
            ),
        )
        self.gateway.submit_wait = asyncio.Event()
        status = await self.coordinator.start_run(
            workspace.id, RunRequest(request_id=uuid4(), preview_digest=preview.digest)
        )
        await self.wait(lambda: bool(self.gateway.requests))
        stored = self.store.run(workspace.id, status.id)
        self.assertEqual(stored.upstream_identity, "http://service")
        self.assertIsNone(stored.status.job_id)
        await self.reopen()
        self.assertEqual(self.store.run(workspace.id, status.id).status.state, "failed")
        self.assertEqual(len(self.gateway.requests), 1)
        self.assertEqual(self.gateway.cancellations, [])

    async def test_local_shutdown_timeout_keeps_last_checkpoint_recoverable(self) -> None:
        self.coordinator = self.coordinate("local")
        record = self.arrange(kind="local")
        self.gateway.poll_wait = asyncio.Event()
        original = asyncio.wait_for
        budgets: list[float] = []

        async def short_wait(awaitable: Awaitable[object], timeout: float) -> object:
            budgets.append(timeout)
            return await original(awaitable, 0.01)

        with patch("value_stream.app.coordinator.asyncio.wait_for", side_effect=short_wait):
            await self.coordinator.close()
        self.assertEqual(budgets, [5])
        self.assertNotIn(self.current(record).status.state, TERMINAL)
        self.assertEqual(self.current(record).service_cursor, 0)
        self.gateway.poll_wait.set()
        await self.reopen(kind="local")
        await self.wait(lambda: self.current(record).status.state in TERMINAL)
        self.assertEqual(self.current(record).status.state, "failed")

    async def test_local_shutdown_unavailable_service_finalizes_without_false_cursor(self) -> None:
        self.coordinator = self.coordinate("local")
        record = self.arrange(kind="local")
        self.gateway.read_error = AppError("SERVICE_UNAVAILABLE", "offline", 503)
        await self.coordinator.close()
        self.assertEqual(self.current(record).status.state, "failed")
        self.assertEqual(self.current(record).service_cursor, 0)


class TestStartup(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def test_factories_imports_contracts_and_help_do_not_start_resources(self) -> None:
        script = """
import concurrent.futures, threading, subprocess
from unittest.mock import patch
with patch.object(concurrent.futures, 'ThreadPoolExecutor', side_effect=AssertionError('executor')), \\
     patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')), \\
     patch.object(subprocess, 'Popen', side_effect=AssertionError('worker')):
    from value_stream.service.app import create_app as service
    from value_stream.app.server import create_app
    from value_stream.app import contracts
    assert create_app().openapi()['openapi'] == '3.1.0'
    assert service().openapi()['openapi'] == '3.1.0'
"""
        environment = dict(os.environ, VALUE_STREAM_DATA_DIR=str(self.root / "untouched"))
        process = subprocess.run(
            [sys.executable, "-c", script],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        for module in ("value_stream.app", "value_stream.service"):
            process = subprocess.run(
                [sys.executable, "-m", module, "--help"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("--database", process.stdout)
            self.assertIn("--data-dir", process.stdout)
        self.assertFalse((self.root / "untouched").exists())

    def test_default_paths_explicit_overrides_and_repeated_lifespans(self) -> None:
        application = create_app(data_dir=self.root, service_database=self.root / "owned.sqlite3")
        self.assertFalse((self.root / "application.sqlite3").exists())
        for _ in range(2):
            with TestClient(application) as client:
                self.assertEqual(client.get("/ready").status_code, 200)
                self.assertEqual(
                    application.state.store.database.config.path, self.root / "application.sqlite3"
                )
                self.assertEqual(
                    application.state.gateway.identity, str(self.root / "owned.sqlite3")
                )
                self.assertTrue(
                    all(
                        isinstance(value, (int, float))
                        for value in client.get("/api/v1/config").json()["limits"].values()
                    )
                )
        # Lifespan release permits an independent owner after both starts.
        with SqliteJobStore(DatabaseConfig("simulation", self.root / "owned.sqlite3")).database:
            pass
        service = create_service(
            database=self.root / "explicit.sqlite3", data_dir=self.root / "unused"
        )
        with TestClient(service):
            self.assertEqual(
                service.state.store.database.config.path, self.root / "explicit.sqlite3"
            )
        self.assertFalse((self.root / "unused").exists())

    def test_initialization_failure_stops_startup_and_closes_every_opened_resource(self) -> None:
        corrupt = self.root / "corrupt.sqlite3"
        corrupt.write_bytes(b"not sqlite")
        with self.assertRaises(DatabaseError):
            with TestClient(create_app(database=corrupt, data_dir=self.root)):
                self.fail("corrupt workspace must stop startup")
        self.assertEqual(corrupt.read_bytes(), b"not sqlite")
        self.assertFalse((self.root / "simulation.sqlite3").exists())
        # An owned-service startup failure leaves retained workspace data usable.
        app = create_app(database=self.root / "good.sqlite3", service_database=corrupt)
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/v1/workspaces").status_code, 201)
            config = client.get("/api/v1/config").json()
            self.assertFalse(config["ready"])
            self.assertTrue(config["error"]["message"])
            self.assertIsNone(local_service._service)
        opened = SqliteWorkspaceStore(DatabaseConfig("application", self.root / "good.sqlite3"))
        opened.close()
        # A gateway close failure still releases the application database.
        gateway = StoreGateway()
        with patch.object(gateway, "close", side_effect=RuntimeError("close failure")):
            with self.assertRaisesRegex(RuntimeError, "close failure"):
                with TestClient(create_app(database=self.root / "close.sqlite3", gateway=gateway)):
                    pass
        opened = SqliteWorkspaceStore(DatabaseConfig("application", self.root / "close.sqlite3"))
        opened.close()

    def test_distinct_files_external_database_rejection_and_singleton_identity(self) -> None:
        with self.assertRaises(ValueError):
            create_app(service_url="http://external", service_database=self.root / "jobs.sqlite3")
        with self.assertRaises(DatabaseError):
            with TestClient(
                create_app(
                    database=self.root / "same.sqlite3", service_database=self.root / "same.sqlite3"
                )
            ):
                self.fail("one file cannot serve both stores")
        first = acquire_local_service(database=self.root / "first.sqlite3")
        try:
            second = acquire_local_service(database=self.root / "first.sqlite3")
            self.assertEqual(second, first)
            release_local_service()
            with self.assertRaisesRegex(RuntimeError, "different database"):
                acquire_local_service(database=self.root / "second.sqlite3")
            with self.assertRaises(DatabaseError):
                with TestClient(create_service(database=self.root / "first.sqlite3")):
                    self.fail("second owner cannot start")
        finally:
            release_local_service()
        self.assertIsNone(local_service._service)
        self.assertFalse((self.root / "second.sqlite3").exists())
        release_local_service()

    def test_real_external_job_finishes_during_application_restart(self) -> None:
        service = _LocalService(DatabaseConfig("simulation", self.root / "external.sqlite3"))
        service.start()
        self.addCleanup(service.stop)
        gate, launched = threading.Event(), threading.Event()
        original = subprocess.Popen

        def launch(
            arguments: list[str], *, stdin: int, stdout: int, stderr: int
        ) -> subprocess.Popen[bytes]:
            launched.set()
            if not gate.wait(timeout=10):
                raise RuntimeError("test worker gate timed out")
            return original(arguments, stdin=stdin, stdout=stdout, stderr=stderr)

        application_db = self.root / "application.sqlite3"
        settings = AppSettings(poll_seconds=0.005)
        scheduler = service.application.state.scheduler
        with (
            patch("value_stream.service.scheduler.subprocess.Popen", side_effect=launch),
            patch.object(scheduler, "cancel", wraps=scheduler.cancel) as cancel,
        ):
            try:
                app = create_app(
                    database=application_db, service_url=service.url, settings=settings
                )
                with TestClient(app) as client:
                    workspace = Workspace.model_validate(client.post("/api/v1/workspaces").json())
                    path = f"/api/v1/workspaces/{workspace.id}"
                    preview = Preview.model_validate(
                        client.put(
                            path + "/editor",
                            json=EditorRequest(
                                expected_revision=0,
                                task_spec=TaskSetSpec(count=2),
                                definitions=[ScenarioDefinition(sweeps={"team_size": [1, 2]})],
                            ).model_dump(mode="json"),
                        ).json()
                    )
                    status = RunStatus.model_validate(
                        client.post(
                            path + "/runs",
                            json=RunRequest(
                                request_id=uuid4(), preview_digest=preview.digest
                            ).model_dump(mode="json"),
                        ).json()
                    )
                    run_path = path + "/runs/" + str(status.id)
                    deadline = time.monotonic() + 5
                    while not client.get(run_path).json()["job_id"]:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    status = RunStatus.model_validate(client.get(run_path).json())
                    self.assertTrue(launched.wait(timeout=5))
                cancel.assert_not_called()
                self.assertIsNotNone(status.job_id)
                gate.set()
                deadline = time.monotonic() + 10
                job_store = service.application.state.store
                while job_store.status(status.job_id).status in ("queued", "running"):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.02)
                app = create_app(
                    database=application_db, service_url=service.url + "/", settings=settings
                )
                with patch.object(scheduler, "submit", side_effect=AssertionError("resubmission")):
                    with TestClient(app) as client:
                        deadline = time.monotonic() + 5
                        while client.get(run_path).json()["state"] not in TERMINAL:
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.01)
                        restored = RunStatus.model_validate(client.get(run_path).json())
                        self.assertEqual(restored.state, "completed")
                        self.assertEqual(sorted(o.cursor for o in restored.outcomes), [1, 2])
                        self.assertEqual(client.get(run_path + "/exports/summary").status_code, 200)
                        self.assertEqual(len(client.get(path).json()["runs"]), 1)
                cancel.assert_not_called()
            finally:
                gate.set()

    def test_cli_forwards_explicit_configuration(self) -> None:
        from value_stream.app import __main__ as app_cli
        from value_stream.service import __main__ as service_cli

        for cli in (app_cli, service_cli):
            options = [
                "program",
                "--host",
                "127.0.0.1",
                "--port",
                "19001",
                "--database",
                str(self.root / "cli.sqlite3"),
                "--data-dir",
                str(self.root),
            ]
            if cli is app_cli:
                options.extend(["--service-database", str(self.root / "jobs.sqlite3")])
            with (
                patch.object(sys, "argv", options),
                patch.object(cli.uvicorn, "run") as run,
                patch.object(cli, "create_app", wraps=cli.create_app) as factory,
                patch.object(Path, "is_file", return_value=True),
            ):
                cli.main()
                self.assertEqual(factory.call_args.kwargs["database"], self.root / "cli.sqlite3")
                self.assertEqual(factory.call_args.kwargs["data_dir"], self.root)
                self.assertEqual(run.call_args.kwargs["workers"], 1)
                self.assertEqual(run.call_args.kwargs["port"], 19001)
        with (
            patch.object(sys, "argv", ["program"]),
            patch.object(Path, "is_file", return_value=False),
        ):
            with self.assertRaises(SystemExit):
                app_cli.main()

    def test_injected_store_skips_database_resolution_and_startup_failure_closes_store(
        self,
    ) -> None:
        from value_stream.app.storage import InMemoryWorkspaceStore

        app_store = InMemoryWorkspaceStore()
        service_store = InMemoryJobStore(ServiceSettings())
        with patch.dict(
            os.environ,
            {"VALUE_STREAM_APP_DATABASE": ":memory:", "VALUE_STREAM_SERVICE_DATABASE": ":memory:"},
        ):
            with TestClient(create_app(store=app_store, gateway=StoreGateway())) as client:
                self.assertEqual(client.post("/api/v1/workspaces").status_code, 201)
            with TestClient(create_service(store=service_store)) as client:
                self.assertEqual(client.get("/health").status_code, 200)
        config = DatabaseConfig("simulation", self.root / "fail.sqlite3")
        with patch(
            "value_stream.service.app.ModelScheduler", side_effect=RuntimeError("scheduler init")
        ):
            with self.assertRaisesRegex(RuntimeError, "scheduler init"):
                with TestClient(create_service(database=config)):
                    pass
        reopened = SqliteJobStore(config)
        reopened.close()

    def test_gateway_repeated_start_close_and_url_identity(self) -> None:
        async def check() -> None:
            external = HttpSimulationGateway("HTTP://Example.COM:80/")
            self.assertEqual(external.identity, "http://example.com")
            await external.start()
            first = external.client
            await external.start()
            self.assertIs(external.client, first)
            await external.close()
            await external.close()
            local = HttpSimulationGateway(database=self.root / "gateway.sqlite3")
            await local.start()
            first_identity = local.identity
            await local.close()
            await local.start()
            self.assertEqual(local.identity, first_identity)
            await local.close()
            with self.assertRaises(ValueError):
                HttpSimulationGateway("http://external", database=self.root / "unused.sqlite3")

        asyncio.run(check())

    def test_owned_local_startup_recovers_and_drains_existing_service_job(self) -> None:
        app_config = DatabaseConfig("application", self.root / "application.sqlite3")
        service_config = DatabaseConfig("simulation", self.root / "simulation.sqlite3")
        settings = AppSettings(poll_seconds=0.005)
        store = SqliteWorkspaceStore(app_config, settings)
        workspace = store.create()
        preview = store.save_editor(
            workspace.id,
            EditorRequest(
                expected_revision=0,
                task_spec=TaskSetSpec(count=2),
                definitions=[ScenarioDefinition(sweeps={"team_size": [1, 2, 3]})],
            ),
        )
        record, _ = store.register(
            workspace.id,
            RunRequest(request_id=uuid4(), preview_digest=preview.digest),
            preview.scenarios,
            store.get(workspace.id).task_sets[0],
        )
        jobs = SqliteJobStore(service_config)
        job = jobs.create(3)
        jobs.start_model(job, 0)
        jobs.finish_model(job, 2, result(record, 2), None)
        store.patch_run(
            workspace.id,
            record.status.id,
            RunChanges(
                job_id=job, upstream_kind="local", upstream_identity=str(service_config.path)
            ),
        )
        jobs.close()
        store.close()
        app = create_app(
            database=app_config.path, service_database=service_config.path, settings=settings
        )
        with patch(
            "value_stream.service.scheduler.subprocess.Popen",
            side_effect=AssertionError("recovered execution"),
        ):
            with TestClient(app) as client:
                path = f"/api/v1/workspaces/{workspace.id}/runs/{record.status.id}"
                deadline = time.monotonic() + 5
                while client.get(path).json()["state"] not in TERMINAL:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                restored = RunStatus.model_validate(client.get(path).json())
                self.assertEqual(restored.state, "failed")
                self.assertEqual(restored.outcomes[2].status, "succeeded")
                self.assertEqual(
                    [o.error.code for o in restored.outcomes if o.error], ["RUN_INTERRUPTED"] * 2
                )
                loaded = app.state.store.run(workspace.id, record.status.id)
                self.assertEqual(loaded.service_cursor, 3)
                self.assertEqual(
                    app.state.store.result(loaded, loaded.status.outcomes[2].scenario.id),
                    result(record, 2),
                )

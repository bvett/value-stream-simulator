"""Shared job contracts, restart recovery, real workers, and abrupt process loss."""

import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from value_stream.service.app import create_app
from value_stream.service.job_store import (
    CapacityExceeded,
    InMemoryJobStore,
    JobOperations,
    _Job,
    JobNotFound,
    SubmissionConflict,
)
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.persistence.database import SqliteDatabase
from value_stream.service.persistence.errors import DatabaseError
from value_stream.service.persistence.job_store import SqliteJobStore
from value_stream.service.schemas import (
    DeveloperInput,
    JobRequest,
    MetadataData,
    ModelError,
    ModelInput,
    OutcomePage,
    QAPoolInput,
    ResultData,
    SummaryData,
    TaskInput,
    ToolchainPoolInput,
)
from value_stream.service.settings import ServiceSettings


def request(count: int = 1) -> JobRequest:
    """Build a small deterministic request for real worker contract checks."""
    return JobRequest(
        tasks=[TaskInput(initial_value=1, story_points=1)],
        models=[
            ModelInput(
                developer_team=[DeveloperInput()],
                deployment_cadence=0,
                qa_testers=QAPoolInput(limit=1),
                toolchain_pool=ToolchainPoolInput(limit=1, deployment_duration=0.1),
            )
            for _ in range(count)
        ],
        seed=123,
    )


def result(index: int = 0) -> ResultData:
    """Return an independently valid result without running the engine."""
    return ResultData(
        model_index=index,
        model=request().models[0],
        summary_result=SummaryData(completion_time=2, total_delivered_value=1, loss=0),
        metadata=MetadataData(event_metadata=[], resource_metadata=[]),
    )


class TestJobAdapters(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = DatabaseConfig("simulation", Path(self.directory.name) / "jobs.sqlite3")

    def stores(self, settings: ServiceSettings | None = None) -> list[JobOperations]:
        settings = settings or ServiceSettings()
        stores = [InMemoryJobStore(settings), SqliteJobStore(self.config, settings)]
        for store in stores:
            self.addCleanup(store.close)
        return stores

    def test_shared_atomic_outcomes_retries_cancellation_and_snapshots(self) -> None:
        for store in self.stores():
            with self.subTest(store=type(store).__name__):
                submission = uuid4()
                job, created = store.reserve(3, submission, "same")
                self.assertTrue(created)
                self.assertEqual(store.reserve(3, submission, "same"), (job, False))
                with self.assertRaises(SubmissionConflict):
                    store.reserve(3, submission, "different")
                self.assertTrue(store.start_model(job, 2))
                self.assertFalse(store.start_model(job, 2))
                store.finish_model(job, 2, result(2), None)
                page = store.page(job, 0)
                page.outcomes.clear()
                self.assertEqual(store.page(job, 0).next_cursor, 1)
                store.cancel(job)
                store.cancel(job)
                store.finish_model(job, 1, result(1), None)
                store.interrupt_unfinished()
                self.assertEqual(store.status(job).status, "cancelled")
                self.assertEqual(
                    [item.model_index for item in store.page(job, 0).outcomes], [2, 0, 1]
                )
                self.assertEqual(len(store.page(job, 1).outcomes), 2)
                self.assertFalse(store.start_model(job, 0))
                with self.assertRaises(JobNotFound):
                    store.status(uuid4())
                with self.assertRaises(ValueError):
                    store.create(0)

    def test_concurrent_completions_and_cancel_races(self) -> None:
        for store in self.stores():
            job = store.create(20)

            def finish(index: int) -> None:
                store.finish_model(job, index, result(index), None)
                store.finish_model(job, index, result(index), None)

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(finish, range(20)))
            self.assertEqual(store.status(job).status, "completed")
            self.assertEqual(
                [item.cursor for item in store.page(job, 0).outcomes], list(range(1, 21))
            )
            job = store.create(20)
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(finish, index) for index in range(20)]
                futures.append(executor.submit(store.cancel, job))
                for future in futures:
                    future.result()
            self.assertEqual(store.page(job, 0).next_cursor, 20)
            self.assertEqual(store.status(job).queued_models, 0)

    def test_limits_interruption_and_invalid_completion_rollback(self) -> None:
        for store in self.stores(ServiceSettings(max_model_outcome_bytes=1, max_retained_jobs=2)):
            first = store.create(2)
            second = store.create(1)
            with self.assertRaises(CapacityExceeded):
                store.create(1)
            store.finish_model(first, 1, result(1), None)
            error = store.page(first, 0).outcomes[0].error
            assert error is not None
            self.assertEqual(error.code, "RESULT_TOO_LARGE")
            with self.assertRaises(ValueError):
                store.finish_model(
                    second, 0, None, ModelError(model_index=1, code="BAD", message="bad")
                )
            self.assertEqual(store.page(second, 0).next_cursor, 0)
            store.finish_model(second, 0, None, None)
            store.interrupt_unfinished()
            store.interrupt_unfinished()
            self.assertEqual(store.status(first).status, "completed_with_errors")
            errors = [
                store.page(first, 0).outcomes[1].error,
                store.page(second, 0).outcomes[0].error,
            ]
            self.assertEqual([e.code for e in errors if e], ["JOB_INTERRUPTED", "WORKER_FAILED"])

    def test_restart_preserves_outcomes_submissions_and_epoch_expiry(self) -> None:
        settings = ServiceSettings(job_ttl_seconds=100, max_retained_jobs=2)
        with patch("time.time", return_value=1_800_000_000):
            store = SqliteJobStore(self.config, settings)
            submission = uuid4()
            job, _ = store.reserve(3, submission, "inputs")
            queued = store.create(1)
            store.start_model(job, 0)
            store.finish_model(job, 2, result(2), None)
            first = store.page(job, 0).outcomes[0]
            store.close()
        with patch("time.time", return_value=1_800_000_050):
            store = SqliteJobStore(self.config, settings)
            self.addCleanup(store.close)
            self.assertEqual(store.reserve(3, submission, "inputs"), (job, False))
            with self.assertRaises(SubmissionConflict):
                store.reserve(3, submission, "changed")
            self.assertEqual(store.page(job, 0).outcomes[0], first)
            self.assertEqual([o.model_index for o in store.page(job, 1).outcomes], [0, 1])
            self.assertEqual(store.status(queued).failed_models, 1)
            with self.assertRaises(CapacityExceeded):
                store.create(1)
            store.close()
        # TTL starts at recovery, not the original queued timestamp.
        with patch("time.time", return_value=1_800_000_151):
            store = SqliteJobStore(self.config, settings)
            self.addCleanup(store.close)
            with self.assertRaises(JobNotFound):
                store.status(job)
            self.assertTrue(store.reserve(1, submission, "changed")[1])

    def test_real_version_one_migration_and_wrong_kind(self) -> None:
        with SqliteDatabase(self.config):
            pass
        store = SqliteJobStore(self.config)
        self.addCleanup(store.close)
        self.assertTrue(
            list(Path(self.directory.name).glob("*.backup*"))
            or list(Path(self.directory.name).glob("*.bak*"))
        )
        self.assertEqual(store.status(store.create(1)).queued_models, 1)
        with self.assertRaises(ValueError):
            SqliteJobStore(DatabaseConfig("application", Path(self.directory.name) / "app.sqlite3"))
        with self.assertRaises(RuntimeError):
            _ = store._sql

    def test_abrupt_process_exit_retains_commits_without_relaunch(self) -> None:
        script = """
import os, sys
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.persistence.job_store import SqliteJobStore
from value_stream.service.schemas import ModelError
store = SqliteJobStore(DatabaseConfig('simulation', sys.argv[1]))
job = store.create(4)
from value_stream.service.schemas import ResultData
store.finish_model(job, 2, ResultData.model_validate_json(sys.argv[2]), None)
store.finish_model(job, 3, None, ModelError(model_index=3,code='COMMITTED',message='kept'))
store.start_model(job, 0)
print(job, flush=True)
os._exit(23)
"""
        process = subprocess.run(
            [sys.executable, "-c", script, str(self.config.path), result(2).model_dump_json()],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 23, process.stderr)
        job = UUID(process.stdout.strip())
        with patch(
            "value_stream.service.scheduler.subprocess.Popen",
            side_effect=AssertionError("relaunch"),
        ):
            store = SqliteJobStore(self.config)
            self.addCleanup(store.close)
            page = store.page(job, 0)
            self.assertEqual(page.outcomes[0].result, result(2))
            self.assertEqual(
                [o.error.code for o in page.outcomes if o.error],
                ["COMMITTED", "JOB_INTERRUPTED", "JOB_INTERRUPTED"],
            )
            self.assertEqual(store.status(job).status, "completed_with_errors")
            store.close()
            store = SqliteJobStore(self.config)
            self.addCleanup(store.close)
            self.assertEqual(store.page(job, 0), page)

    def test_result_budgets_atomic_rollback_and_polling_without_payload_reads(self) -> None:
        size = len(result().model_dump_json().encode("utf-8"))
        for store in self.stores(
            ServiceSettings(max_retained_bytes=size, max_job_outcome_bytes=size)
        ):
            job, _ = store.reserve(2, uuid4(), "inputs")
            store.finish_model(job, 0, result(), None)
            store.finish_model(job, 1, result(1), None)
            error = store.page(job, 1).outcomes[0].error
            assert error is not None
            self.assertEqual(error.code, "RESULT_TOO_LARGE")
            with self.assertRaises(CapacityExceeded):
                store.create(1)
        # Use an independent database to exercise a failure after real row updates.
        config = DatabaseConfig("simulation", Path(self.directory.name) / "rollback.sqlite3")
        store = SqliteJobStore(config)
        self.addCleanup(store.close)
        job = store.create(2)
        original = store._save

        def fail_after_write(snapshot: _Job) -> None:
            original(snapshot)
            raise RuntimeError("after counters and outcome SQL")

        with patch.object(store, "_save", side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                store.finish_model(job, 0, result(), None)
        self.assertEqual(store.status(job).last_cursor, 0)
        with store.database.read() as connection:
            self.assertEqual(connection.execute("SELECT result_bytes FROM jobs").fetchone()[0], 0)
        store.finish_model(job, 0, result(), None)
        with patch.object(store.payloads, "deserialize", side_effect=AssertionError("loaded JSON")):
            self.assertEqual(store.status(job).succeeded_models, 1)
            self.assertTrue(store.start_model(job, 1))
            self.assertEqual(store.page(job, 1).outcomes, [])
        for index in (-1, 2):
            with self.assertRaises(IndexError):
                store.start_model(job, index)
            with self.assertRaises(IndexError):
                store.finish_model(job, index, None, None)

    def test_recovery_failure_rolls_back_and_releases_ownership(self) -> None:
        store = SqliteJobStore(self.config)
        job = store.create(2)
        store.finish_model(job, 1, result(1), None)
        before = store.page(job, 0)
        store.close()
        original = SqliteJobStore._save

        def fail_after_write(adapter: SqliteJobStore, snapshot: _Job) -> None:
            original(adapter, snapshot)
            raise RuntimeError("recovery write failed")

        with patch.object(SqliteJobStore, "_save", new=fail_after_write):
            with self.assertRaises(RuntimeError):
                SqliteJobStore(self.config)
        with sqlite3.connect(self.config.path) as connection:
            self.assertEqual(connection.execute("SELECT last_cursor FROM jobs").fetchone()[0], 1)
        store = SqliteJobStore(self.config)
        self.addCleanup(store.close)
        self.assertEqual(store.page(job, 0).outcomes[0], before.outcomes[0])
        self.assertEqual(store.status(job).last_cursor, 2)

    def test_corrupt_relational_state_and_future_payload_stop_startup(self) -> None:
        mutations = [
            "UPDATE jobs SET last_cursor=99",
            "UPDATE job_models SET byte_count=99 WHERE model_index=0",
            "UPDATE jobs SET state='completed'",
            "UPDATE jobs SET payload_version=999",
        ]
        for index, statement in enumerate(mutations):
            with self.subTest(statement=statement):
                config = DatabaseConfig(
                    "simulation", Path(self.directory.name) / f"corrupt{index}.sqlite3"
                )
                store = SqliteJobStore(config)
                job = store.create(2)
                store.finish_model(job, 0, result(), None)
                store.close()
                with sqlite3.connect(config.path) as connection:
                    connection.execute(statement)
                before = config.path.read_bytes()
                with self.assertRaises(DatabaseError):
                    SqliteJobStore(config)
                self.assertEqual(config.path.read_bytes(), before)

    def test_graceful_http_shutdown_interrupts_and_releases_database(self) -> None:
        store = SqliteJobStore(self.config)
        application = create_app(store=store)
        with TestClient(application) as client:
            job = store.create(2)
            store.finish_model(job, 1, result(1), None)
            store.start_model(job, 0)
            self.assertEqual(client.get(f"/v1/simulation-jobs/{job}").status_code, 200)
            slow = request()
            slow.models[0].toolchain_pool = ToolchainPoolInput(
                limit=1, deployment_duration=0.1, failure_rate=1
            )
            submitted = client.post("/v1/simulation-jobs", json=slow.model_dump(mode="json"))
            self.assertEqual(submitted.status_code, 202)
            running = UUID(submitted.json()["job_id"])
            deadline = time.monotonic() + 5
            while not application.state.scheduler._processes:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
        self.assertFalse(application.state.scheduler._processes)
        reopened = SqliteJobStore(self.config)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.status(job).status, "completed_with_errors")
        self.assertEqual(reopened.page(job, 0).outcomes[0].result, result(1))
        self.assertEqual(reopened.page(job, 0).next_cursor, 2)
        self.assertEqual(reopened.status(running).failed_models, 1)
        error = reopened.page(running, 0).outcomes[0].error
        assert error is not None
        self.assertEqual(error.code, "JOB_INTERRUPTED")

    def test_http_real_workers_and_reopen_without_resubmission(self) -> None:
        for store in self.stores():
            with TestClient(create_app(store=store)) as client:
                body = request(2).model_dump(mode="json")
                body["submission_id"] = str(uuid4())
                submitted = client.post("/v1/simulation-jobs", json=body)
                self.assertEqual(submitted.status_code, 202, submitted.text)
                job = submitted.json()["job_id"]
                deadline = time.monotonic() + 10
                while client.get(f"/v1/simulation-jobs/{job}").json()["status"] in (
                    "queued",
                    "running",
                ):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.02)
                page = client.get(f"/v1/simulation-jobs/{job}/outcomes").json()
                self.assertEqual(
                    [o.status for o in OutcomePage.model_validate(page).outcomes], ["succeeded"] * 2
                )
            if isinstance(store, SqliteJobStore):
                store = SqliteJobStore(self.config)
                self.addCleanup(store.close)
            application = create_app(store=store)
            with TestClient(application) as client:
                self.assertEqual(client.get(f"/v1/simulation-jobs/{job}/outcomes").json(), page)
                with patch.object(
                    application.state.scheduler,
                    "submit",
                    side_effect=AssertionError("retry launch"),
                ):
                    retry = client.post("/v1/simulation-jobs", json=body)
                    self.assertEqual(retry.json()["job_id"], job)

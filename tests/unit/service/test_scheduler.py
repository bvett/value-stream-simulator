"""Worker failure, queue ownership, and shutdown interruption contracts."""

import json
import subprocess
import unittest
from concurrent.futures import Future
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from value_stream.service.job_store import InMemoryJobStore, JobNotFound
from value_stream.service.scheduler import ModelScheduler
from value_stream.service.schemas import (
    DeveloperInput,
    JobRequest,
    JobStatus,
    MetadataData,
    ModelInput,
    QAPoolInput,
    ResultData,
    SummaryData,
    TaskInput,
    ToolchainPoolInput,
)
from value_stream.service.settings import ServiceSettings


def request() -> JobRequest:
    """Supply one small model and explicit per-model seed."""
    return JobRequest(
        tasks=[TaskInput(initial_value=1, story_points=1)],
        models=[
            ModelInput(
                developer_team=[DeveloperInput()],
                deployment_cadence=0,
                qa_testers=QAPoolInput(limit=1),
                toolchain_pool=ToolchainPoolInput(limit=1, deployment_duration=0),
            )
        ],
        model_seeds=[12],
    )


class TestScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryJobStore(ServiceSettings())
        self.scheduler = ModelScheduler(self.store, self.store.settings)
        self.addCleanup(self.scheduler.close)

    def test_worker_errors_and_success_are_indexed(self) -> None:
        result = ResultData(
            model_index=0,
            model=request().models[0],
            summary_result=SummaryData(completion_time=1, total_delivered_value=1, loss=0),
            metadata=MetadataData(event_metadata=[], resource_metadata=[]),
        )
        cases: list[tuple[object, int, str | None]] = [
            ({"result": result.model_dump(mode="json")}, 0, None),
            (
                {"error": {"model_index": 0, "code": "MODEL_FAILED", "message": "bad"}},
                0,
                "MODEL_FAILED",
            ),
            ({"error": {"model_index": 1, "code": "BAD", "message": "bad"}}, 0, "WORKER_FAILED"),
            (
                {"result": result.model_copy(update={"model_index": 1}).model_dump(mode="json")},
                0,
                "WORKER_FAILED",
            ),
            ({}, 0, "WORKER_FAILED"),
            ({}, 1, "WORKER_FAILED"),
        ]
        for output, returncode, code in cases:
            with self.subTest(output=output, returncode=returncode):
                job = self.store.create(1)
                process = MagicMock()
                process.communicate.return_value = (json.dumps(output).encode(), b"")
                process.returncode = returncode
                process.poll.return_value = returncode
                with patch("value_stream.service.scheduler.subprocess.Popen", return_value=process):
                    self.scheduler._run_model(job, request(), 0)
                outcome = self.store.page(job, 0).outcomes[0]
                self.assertEqual(outcome.error.code if outcome.error else None, code)
                payload = json.loads(process.communicate.call_args.kwargs["input"])
                self.assertEqual(payload["request"]["model_seeds"], [12])

    def test_timeout_oversize_launch_failure_and_stop_escalation(self) -> None:
        job = self.store.create(1)
        process = MagicMock()
        process.poll.side_effect = [None, 0]
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("worker", 1),
            subprocess.TimeoutExpired("worker", 5),
            (b"", b""),
        ]
        with patch("value_stream.service.scheduler.subprocess.Popen", return_value=process):
            self.scheduler._run_model(job, request(), 0)
        process.kill.assert_called_once()
        error = self.store.page(job, 0).outcomes[0].error
        assert error is not None
        self.assertEqual(error.code, "MODEL_TIMEOUT")
        job = self.store.create(1)
        process = MagicMock()
        process.returncode = 0
        process.poll.return_value = 0
        process.communicate.return_value = (
            b"x" * (self.store.settings.max_model_outcome_bytes + 4097),
            b"",
        )
        with patch("value_stream.service.scheduler.subprocess.Popen", return_value=process):
            self.scheduler._run_model(job, request(), 0)
        self.assertEqual(self.store.status(job).failed_models, 1)
        job = self.store.create(1)
        with patch(
            "value_stream.service.scheduler.subprocess.Popen", side_effect=OSError("launch failed")
        ):
            self.scheduler._run_model(job, request(), 0)
        self.assertEqual(self.store.status(job).failed_models, 1)
        self.scheduler._run_model(uuid4(), request(), 0)
        self.scheduler._run_model(job, request(), 0)

    def test_shutdown_finalizes_before_late_callbacks_and_clears_queue(self) -> None:
        job = self.store.create(2)
        cancelled = self.store.create(1)
        self.store.cancel(cancelled)
        self.store.finish_model(job, 1, None, None)
        self.scheduler._pending_jobs.append((job, request()))
        process = MagicMock()
        process.poll.return_value = None
        self.scheduler._processes[(job, 0)] = process
        future: Future[None] = Future()
        self.scheduler._futures[job] = [future]
        self.scheduler.close()
        self.scheduler.close()
        self.store.finish_model(job, 0, None, None)
        self.assertEqual(self.store.status(job).failed_models, 2)
        self.assertEqual(self.store.status(cancelled).status, "cancelled")
        error = self.store.page(job, 1).outcomes[0].error
        assert error is not None
        self.assertEqual(error.code, "JOB_INTERRUPTED")
        process.terminate.assert_called_once()
        self.assertTrue(future.cancelled())
        with self.assertRaises(RuntimeError):
            self.scheduler.submit(job, request())
        # A worker already starting when shutdown wins must stop before communicate.
        self.store = InMemoryJobStore(ServiceSettings())
        self.scheduler.store = self.store
        job = self.store.create(1)
        process = MagicMock()
        process.poll.return_value = 0
        with patch("value_stream.service.scheduler.subprocess.Popen", return_value=process):
            self.scheduler._run_model(job, request(), 0)
        process.terminate.assert_called_once()

    def test_queue_skips_cancelled_and_expired_jobs_and_cancels_workers(self) -> None:
        active, cancelled, expired, pending = [self.store.create(1) for _ in range(4)]
        self.store.cancel(cancelled)
        self.scheduler._pending_jobs.extend(
            [(cancelled, request()), (expired, request()), (pending, request())]
        )
        future: Future[None] = Future()
        future.set_result(None)
        self.scheduler._futures[active] = [future]
        self.scheduler._active_jobs.add(active)
        original = self.store.status

        def status(job_id: UUID) -> JobStatus:
            if job_id == expired:
                raise JobNotFound(str(job_id))
            return original(job_id)

        with (
            patch.object(self.store, "status", side_effect=status),
            patch.object(self.scheduler, "_start_job") as start,
        ):
            self.scheduler._forget_finished(active)
            start.assert_called_once_with(pending, request())
        self.scheduler._pending_jobs.append((pending, request()))
        future = Future()
        self.scheduler._futures[pending] = [future]
        process = MagicMock()
        process.poll.return_value = None
        self.scheduler._processes[(pending, 0)] = process
        self.scheduler.cancel(pending)
        self.assertTrue(future.cancelled())
        process.terminate.assert_called_once()
        self.assertFalse(self.scheduler._pending_jobs)

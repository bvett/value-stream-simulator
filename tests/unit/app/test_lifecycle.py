import asyncio
import csv
import io
import unittest
from typing import Callable
from unittest.mock import patch
from uuid import UUID, uuid4
from value_stream.app.coordinator import RunCoordinator
from value_stream.app.storage import InMemoryWorkspaceStore, RunChanges, RunRecord
from value_stream.app.schemas import (
    EditorRequest,
    RunRequest,
    RunStatus,
    TaskSetSpec,
    ScenarioDefinition,
    Status,
    TERMINAL,
)
from value_stream.app.settings import AppSettings
from value_stream.app.errors import AppError
from value_stream.app.exports import export_csv
from value_stream.service.schemas import (
    JobAccepted,
    JobRequest,
    JobStatus,
    OutcomePage,
    OutcomeData,
    ResultData,
    SummaryData,
    MetadataData,
    ModelError,
)


class ControlledGateway:
    def __init__(self) -> None:
        self.requests: list[JobRequest] = []
        self.job = uuid4()
        self.pages: list[OutcomeData] = []
        self.cancelled = False
        self.lost_submission = False
        self.fail_reads = False
        self.closed = False

    async def start(self) -> None:
        pass

    async def ready(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def submit(self, request: JobRequest) -> JobAccepted:
        if not self.requests:
            self.requests.append(request)
            if self.lost_submission:
                raise AppError("SERVICE_UNAVAILABLE", "lost response", 503)
        return JobAccepted(job_id=self.job, status="queued", status_url="")

    async def status(self, job_id: UUID) -> JobStatus:
        if self.fail_reads:
            raise AppError("SERVICE_UNAVAILABLE", "disconnected", 503)
        n = len(self.requests[0].models)
        outcomes = self.current()
        return JobStatus(
            job_id=self.job,
            status=(
                "cancelled"
                if self.cancelled
                else (
                    "completed_with_errors"
                    if len(outcomes) == n and any(o.status == "failed" for o in outcomes)
                    else "completed" if len(outcomes) == n else "running"
                )
            ),
            total_models=n,
            queued_models=n - len(outcomes),
            running_models=0,
            succeeded_models=sum(o.status == "succeeded" for o in outcomes),
            failed_models=sum(o.status == "failed" for o in outcomes),
            cancelled_models=sum(o.status == "cancelled" for o in outcomes),
            last_cursor=len(outcomes),
        )

    def current(self) -> list[OutcomeData]:
        outcomes = list(self.pages)
        if self.cancelled:
            for i in range(len(self.requests[0].models)):
                if not any(o.model_index == i for o in outcomes):
                    outcomes.append(
                        OutcomeData(
                            cursor=len(outcomes) + 1, model_index=i, status=Status.CANCELLED
                        )
                    )
        return outcomes

    async def outcomes(self, job_id: UUID, after: int) -> OutcomePage:
        values = self.current()
        return OutcomePage(
            outcomes=[o for o in values if o.cursor > after], next_cursor=len(values)
        )

    async def cancel(self, job_id: UUID) -> JobStatus:
        self.cancelled = True
        return await self.status(job_id)

    def succeed(self, index: int) -> None:
        self.pages.append(
            OutcomeData(
                cursor=len(self.pages) + 1,
                model_index=index,
                status=Status.SUCCEEDED,
                result=ResultData(
                    model_index=index,
                    model=self.requests[0].models[index],
                    summary_result=SummaryData(
                        completion_time=3, total_delivered_value=5, loss=-0.5
                    ),
                    metadata=MetadataData(event_metadata=[], resource_metadata=[]),
                ),
            )
        )


class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = InMemoryWorkspaceStore(
            AppSettings(poll_seconds=0.005, retry_seconds=0.03, min_interactive_seconds=0.001)
        )
        self.gateway = ControlledGateway()
        self.coordinator = RunCoordinator(self.store, self.gateway)
        self.workspace = self.store.create()
        self.preview = self.store.save_editor(
            self.workspace.id,
            EditorRequest(
                expected_revision=0,
                task_spec=TaskSetSpec(count=10),
                definitions=[ScenarioDefinition(sweeps={"team_size": [2, 4, 6]})],
            ),
        )

    async def asyncTearDown(self) -> None:
        await self.coordinator.close()

    async def wait(self, condition: Callable[[], bool]) -> None:
        for _ in range(100):
            if condition():
                return
            await asyncio.sleep(0.005)
        self.fail("condition did not become true")

    async def start(self) -> tuple[RunStatus, RunRequest]:
        request = RunRequest(
            request_id=uuid4(),
            preview_digest=self.preview.digest,
            name="=danger, comparison",
        )
        status = await self.coordinator.start_run(self.workspace.id, request)
        await self.wait(lambda: bool(self.gateway.requests))
        return status, request

    async def test_partial_results_cancel_refresh_and_csv(self) -> None:
        status, request = await self.start()
        self.gateway.succeed(2)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.outcomes[2].status
            == "succeeded"
        )
        status = self.store.run(self.workspace.id, status.id).status
        again = await self.coordinator.start_run(self.workspace.id, request)
        self.assertEqual(status.id, again.id)
        await self.coordinator.cancel_run(self.workspace.id, status.id)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state in TERMINAL
        )
        status = self.store.run(self.workspace.id, status.id).status
        self.assertEqual(
            [o.status for o in status.outcomes], ["cancelled", "cancelled", "succeeded"]
        )
        self.assertEqual(self.store.get(self.workspace.id).runs[0].outcomes[2].loss_percent, 50)
        record = self.store.run(self.workspace.id, status.id)
        rows = list(csv.DictReader(io.StringIO("".join(export_csv(self.store, record, "summary")))))
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["comparison_name"].startswith("'="))
        self.assertEqual(rows[2]["value_lost_percent"], "50.0")

    async def test_lost_submit_response_retries_same_id(self) -> None:
        self.gateway.lost_submission = True
        status, _ = await self.start()
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.job_id is not None
        )
        status = self.store.run(self.workspace.id, status.id).status
        self.assertEqual(len(self.gateway.requests), 1)
        for i in range(3):
            self.gateway.succeed(i)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state == "completed"
        )
        status = self.store.run(self.workspace.id, status.id).status

    async def test_cache_and_immutable_interactive_seed(self) -> None:
        status, _ = await self.start()
        for i in range(3):
            self.gateway.succeed(i)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state == "completed"
        )
        status = self.store.run(self.workspace.id, status.id).status
        await asyncio.sleep(0.005)
        request = RunRequest(
            request_id=uuid4(),
            preview_digest="",
            intent="interactive",
            source_run_id=status.id,
            property="deployment_cadence",
            value=5,
            family_value=5,
        )
        second = await self.coordinator.start_run(self.workspace.id, request)
        await self.wait(
            lambda: self.store.run(self.workspace.id, second.id).status.state == "completed"
        )
        second = self.store.run(self.workspace.id, second.id).status
        self.assertTrue(all(o.cached for o in second.outcomes))
        self.assertEqual(
            [o.scenario.execution_seed for o in status.outcomes],
            [o.scenario.execution_seed for o in second.outcomes],
        )
        self.assertTrue(all(o.scenario.revision == 1 for o in status.outcomes))
        self.store.comparison(self.workspace.id, second.id, "pin")
        self.assertTrue(self.store.get(self.workspace.id).runs[-1].pinned)

    async def test_connection_budget_preserves_run_and_resume(self) -> None:
        self.gateway.fail_reads = True
        status, _ = await self.start()
        await self.wait(lambda: self.store.run(self.workspace.id, status.id).status.retry_paused)
        status = self.store.run(self.workspace.id, status.id).status
        self.assertEqual(status.state, "reconnecting")
        self.gateway.fail_reads = False
        for i in range(3):
            self.gateway.succeed(i)
        self.coordinator.resume(self.workspace.id, status.id)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state == "completed"
        )
        status = self.store.run(self.workspace.id, status.id).status

    async def test_resume_as_soon_as_connection_budget_expires(self) -> None:
        self.gateway.fail_reads = True
        status, _ = await self.start()
        original_patch = self.store.patch_run
        resumed = False

        def resume_on_pause(owner: UUID, run_id: UUID, changes: RunChanges) -> RunRecord:
            nonlocal resumed
            record = original_patch(owner, run_id, changes)
            if changes.retry_paused:
                resumed = True
                self.gateway.fail_reads = False
                for i in range(3):
                    self.gateway.succeed(i)
                self.coordinator.resume(owner, run_id)
            return record

        with patch.object(self.store, "patch_run", side_effect=resume_on_pause):
            await self.wait(
                lambda: self.store.run(self.workspace.id, status.id).status.state == "completed"
            )
        self.assertTrue(resumed)

    async def test_failure_does_not_discard_success(self) -> None:
        status, _ = await self.start()
        self.gateway.succeed(2)
        self.gateway.pages.append(
            OutcomeData(
                cursor=2,
                model_index=0,
                status=Status.FAILED,
                error=ModelError(model_index=0, code="MODEL_FAILED", message="fixture error"),
            )
        )
        self.gateway.succeed(1)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state
            == "completed_with_errors"
        )
        status = self.store.run(self.workspace.id, status.id).status
        assert status.outcomes[0].error is not None
        self.assertEqual(status.outcomes[0].error.code, "MODEL_FAILED")
        self.assertEqual(len(self.store.run(self.workspace.id, status.id).results), 2)

    async def test_superseded_interactive_completion_cannot_replace_latest(self) -> None:
        baseline, _ = await self.start()
        for i in range(3):
            self.gateway.succeed(i)
        await self.wait(
            lambda: self.store.run(self.workspace.id, baseline.id).status.state == "completed"
        )
        baseline = self.store.run(self.workspace.id, baseline.id).status
        await asyncio.sleep(0.005)
        self.gateway = ControlledGateway()
        self.coordinator.gateway = self.gateway
        request = RunRequest(
            request_id=uuid4(),
            preview_digest="",
            intent="interactive",
            source_run_id=baseline.id,
            property="deployment_cadence",
            family_value=5,
            value=1,
        )
        first = await self.coordinator.start_run(self.workspace.id, request)
        await self.wait(lambda: bool(self.gateway.requests))
        self.gateway.succeed(0)
        next_request = request.model_copy(update={"request_id": uuid4(), "value": 2.0})
        with self.assertRaisesRegex(AppError, "previous interactive job"):
            await self.coordinator.start_run(self.workspace.id, next_request)
        await self.wait(
            lambda: self.store.run(self.workspace.id, first.id).status.state == "cancelled"
        )
        first = self.store.run(self.workspace.id, first.id).status
        self.assertTrue(first.superseded)
        self.assertEqual(first.outcomes[0].status, "succeeded")
        self.gateway = ControlledGateway()
        self.coordinator.gateway = self.gateway
        latest = await self.coordinator.start_run(self.workspace.id, next_request)
        self.store.complete_outcomes(self.workspace.id, first.id, [], terminal_state="cancelled")
        workspace = self.store.get(self.workspace.id)
        self.assertEqual(workspace.baseline_id, baseline.id)
        self.assertEqual(workspace.latest_id, latest.id)
        self.assertEqual(baseline.outcomes[0].scenario.settings.deployment_cadence, 5)

    async def test_revisions_and_admission(self) -> None:
        with self.assertRaises(AppError):
            self.store.save_editor(
                self.workspace.id,
                EditorRequest(
                    expected_revision=0,
                    task_spec=TaskSetSpec(),
                    definitions=[ScenarioDefinition()],
                ),
            )
        status, _ = await self.start()
        with self.assertRaisesRegex(AppError, "current run"):
            await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(request_id=uuid4(), preview_digest=self.preview.digest),
            )
        self.assertEqual(self.store.run(self.workspace.id, status.id).status.state, "running")

    async def test_lost_job_preserves_a_previously_committed_success(self) -> None:
        status, _ = await self.start()
        self.gateway.succeed(1)
        await self.wait(lambda: bool(self.store.run(self.workspace.id, status.id).results))
        with patch.object(
            self.gateway, "status", side_effect=AppError("JOB_NOT_FOUND", "expired", 404)
        ):
            await self.wait(
                lambda: self.store.run(self.workspace.id, status.id).status.state == "failed"
            )
        record = self.store.run(self.workspace.id, status.id)
        self.assertEqual(record.status.outcomes[1].status, Status.SUCCEEDED)
        self.assertEqual(len(record.results), 1)
        assert record.status.error is not None
        self.assertEqual(record.status.error.code, "SERVICE_JOB_LOST")
        self.assertEqual(record.reservation, 0)

    async def test_unexpected_gateway_failure_is_persisted(self) -> None:
        with patch.object(self.gateway, "status", side_effect=RuntimeError("unexpected")):
            status, _ = await self.start()
            await self.wait(
                lambda: self.store.run(self.workspace.id, status.id).status.state == "failed"
            )
        record = self.store.run(self.workspace.id, status.id)
        assert record.status.error is not None
        self.assertEqual(record.status.error.code, "INTERNAL_ERROR")
        self.assertTrue(all(o.status == Status.FAILED for o in record.status.outcomes))

    async def test_invalid_service_index_is_rejected(self) -> None:
        status, _ = await self.start()
        self.gateway.pages.append(OutcomeData(cursor=1, model_index=99, status=Status.CANCELLED))
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state == "failed"
        )
        record = self.store.run(self.workspace.id, status.id)
        assert record.status.error is not None
        self.assertEqual(record.status.error.code, "SERVICE_INVALID_RESPONSE")

    async def test_expanded_request_limit_is_persisted_before_submission(self) -> None:
        from dataclasses import replace

        self.store.settings = replace(self.store.settings, max_body_bytes=1)
        status = await self.coordinator.start_run(
            self.workspace.id, RunRequest(request_id=uuid4(), preview_digest=self.preview.digest)
        )
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state == "failed"
        )
        record = self.store.run(self.workspace.id, status.id)
        assert record.status.error is not None
        self.assertEqual(record.status.error.code, "BODY_TOO_LARGE")
        self.assertEqual(self.gateway.requests, [])

    async def test_invalid_interactive_requests_and_closed_admission(self) -> None:
        self.coordinator.closed = True
        with self.assertRaises(AppError):
            await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(request_id=uuid4(), preview_digest=self.preview.digest),
            )
        self.coordinator.closed = False
        with self.assertRaises(AppError):
            await self.coordinator.start_run(
                self.workspace.id, RunRequest(request_id=uuid4(), preview_digest="stale")
            )
        with self.assertRaises(AppError):
            await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(request_id=uuid4(), preview_digest="", intent="interactive"),
            )
        status, _ = await self.start()
        with self.assertRaises(AppError):
            await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(
                    request_id=uuid4(),
                    preview_digest="",
                    intent="interactive",
                    source_run_id=status.id,
                    property="deployment_cadence",
                    family_value=5,
                    value=1,
                ),
            )
        for index in range(3):
            self.gateway.succeed(index)
        await self.wait(
            lambda: self.store.run(self.workspace.id, status.id).status.state == "completed"
        )
        with self.assertRaises(AppError):
            await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(
                    request_id=uuid4(),
                    preview_digest="",
                    intent="interactive",
                    source_run_id=status.id,
                    property="deployment_cadence",
                    family_value=999,
                    value=1,
                ),
            )
        self.store.save_editor(
            self.workspace.id,
            EditorRequest(
                expected_revision=1,
                task_spec=TaskSetSpec(count=2),
                definitions=[ScenarioDefinition()],
            ),
        )
        with self.assertRaises(AppError):
            await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(
                    request_id=uuid4(),
                    preview_digest="",
                    intent="interactive",
                    source_run_id=status.id,
                    property="deployment_cadence",
                    family_value=5,
                    value=1,
                ),
            )
        finished = await self.coordinator.cancel_run(self.workspace.id, status.id)
        self.assertEqual(finished.state, "completed")
        self.assertEqual(self.coordinator.resume(self.workspace.id, status.id).state, "completed")

    async def test_cancel_during_submission_survives_the_acceptance_patch(self) -> None:
        accepted = asyncio.Event()
        release = asyncio.Event()
        submit = self.gateway.submit

        async def delayed(request: JobRequest) -> JobAccepted:
            value = await submit(request)
            accepted.set()
            await release.wait()
            return value

        with patch.object(self.gateway, "submit", side_effect=delayed):
            status = await self.coordinator.start_run(
                self.workspace.id,
                RunRequest(request_id=uuid4(), preview_digest=self.preview.digest),
            )
            await asyncio.wait_for(accepted.wait(), timeout=1)
            await self.coordinator.cancel_run(self.workspace.id, status.id)
            release.set()
            await self.wait(
                lambda: self.store.run(self.workspace.id, status.id).status.state == "cancelled"
            )
        record = self.store.run(self.workspace.id, status.id)
        self.assertTrue(record.status.cancel_requested)
        self.assertEqual(record.status.job_id, self.gateway.job)
        self.assertTrue(all(o.status == Status.CANCELLED for o in record.status.outcomes))

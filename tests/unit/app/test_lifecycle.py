import asyncio
import csv
import io
import unittest
from uuid import uuid4
from value_stream.app.coordinator import RunCoordinator
from value_stream.app.storage import InMemoryWorkspaceStore
from value_stream.app.schemas import (
    EditorRequest,
    RunRequest,
    TaskSetSpec,
    ScenarioDefinition,
    TERMINAL,
)
from value_stream.app.settings import AppSettings
from value_stream.app.errors import AppError
from value_stream.app.exports import export_csv
from value_stream.service.schemas import (
    JobAccepted,
    JobStatus,
    OutcomePage,
    OutcomeData,
    ResultData,
    SummaryData,
    MetadataData,
    ModelError,
)


class ControlledGateway:
    def __init__(self):
        self.requests = []
        self.job = uuid4()
        self.pages = []
        self.cancelled = False
        self.lost_submission = False
        self.fail_reads = False
        self.closed = False

    async def start(self):
        pass

    async def ready(self):
        pass

    async def close(self):
        self.closed = True

    async def submit(self, request):
        if not self.requests:
            self.requests.append(request)
            if self.lost_submission:
                raise AppError("SERVICE_UNAVAILABLE", "lost response", 503)
        return JobAccepted(job_id=self.job, status="queued", status_url="")

    async def status(self, job_id):
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
                    if len(outcomes) == n
                    and any(o.status == "failed" for o in outcomes)
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

    def current(self):
        outcomes = list(self.pages)
        if self.cancelled:
            for i in range(len(self.requests[0].models)):
                if not any(o.model_index == i for o in outcomes):
                    outcomes.append(
                        OutcomeData(
                            cursor=len(outcomes) + 1, model_index=i, status="cancelled"
                        )
                    )
        return outcomes

    async def outcomes(self, job_id, after):
        values = self.current()
        return OutcomePage(
            outcomes=[o for o in values if o.cursor > after], next_cursor=len(values)
        )

    async def cancel(self, job_id):
        self.cancelled = True

    def succeed(self, index):
        self.pages.append(
            OutcomeData(
                cursor=len(self.pages) + 1,
                model_index=index,
                status="succeeded",
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
    async def asyncSetUp(self):
        self.store = InMemoryWorkspaceStore(
            AppSettings(
                poll_seconds=0.005, retry_seconds=0.03, min_interactive_seconds=0.001
            )
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

    async def asyncTearDown(self):
        await self.coordinator.close()

    async def wait(self, condition):
        for _ in range(100):
            if condition():
                return
            await asyncio.sleep(0.005)
        self.fail("condition did not become true")

    async def start(self):
        request = RunRequest(
            request_id=uuid4(),
            preview_digest=self.preview.digest,
            name="=danger, comparison",
        )
        status = await self.coordinator.start_run(self.workspace.id, request)
        await self.wait(lambda: bool(self.gateway.requests))
        return status, request

    async def test_partial_results_cancel_refresh_and_csv(self):
        status, request = await self.start()
        self.gateway.succeed(2)
        await self.wait(lambda: status.outcomes[2].status == "succeeded")
        again = await self.coordinator.start_run(self.workspace.id, request)
        self.assertEqual(status.id, again.id)
        await self.coordinator.cancel_run(self.workspace.id, status.id)
        await self.wait(lambda: status.state in TERMINAL)
        self.assertEqual(
            [o.status for o in status.outcomes], ["cancelled", "cancelled", "succeeded"]
        )
        self.assertEqual(
            self.store.get(self.workspace.id).runs[0].outcomes[2].loss_percent, 50
        )
        record = self.store.run(self.workspace.id, status.id)
        rows = list(
            csv.DictReader(
                io.StringIO("".join(export_csv(self.store, record, "summary")))
            )
        )
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["comparison_name"].startswith("'="))
        self.assertEqual(rows[2]["value_lost_percent"], "50.0")

    async def test_lost_submit_response_retries_same_id(self):
        self.gateway.lost_submission = True
        status, _ = await self.start()
        await self.wait(lambda: status.job_id is not None)
        self.assertEqual(len(self.gateway.requests), 1)
        for i in range(3):
            self.gateway.succeed(i)
        await self.wait(lambda: status.state == "completed")

    async def test_cache_and_immutable_interactive_seed(self):
        status, _ = await self.start()
        for i in range(3):
            self.gateway.succeed(i)
        await self.wait(lambda: status.state == "completed")
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
        await self.wait(lambda: second.state == "completed")
        self.assertTrue(all(o.cached for o in second.outcomes))
        self.assertEqual(
            [o.scenario.execution_seed for o in status.outcomes],
            [o.scenario.execution_seed for o in second.outcomes],
        )
        self.assertTrue(all(o.scenario.revision == 1 for o in status.outcomes))
        self.store.comparison(self.workspace.id, second.id, "pin")
        self.assertTrue(self.store.get(self.workspace.id).runs[-1].pinned)

    async def test_connection_budget_preserves_run_and_resume(self):
        self.gateway.fail_reads = True
        status, _ = await self.start()
        await self.wait(lambda: status.retry_paused)
        self.assertEqual(status.state, "reconnecting")
        self.gateway.fail_reads = False
        for i in range(3):
            self.gateway.succeed(i)
        self.coordinator.resume(self.workspace.id, status.id)
        await self.wait(lambda: status.state == "completed")

    async def test_failure_does_not_discard_success(self):
        status, _ = await self.start()
        self.gateway.succeed(2)
        self.gateway.pages.append(
            OutcomeData(
                cursor=2,
                model_index=0,
                status="failed",
                error=ModelError(
                    model_index=0, code="MODEL_FAILED", message="fixture error"
                ),
            )
        )
        self.gateway.succeed(1)
        await self.wait(lambda: status.state == "completed_with_errors")
        self.assertEqual(status.outcomes[0].error.code, "MODEL_FAILED")
        self.assertEqual(len(self.store.run(self.workspace.id, status.id).results), 2)

    async def test_superseded_interactive_completion_cannot_replace_latest(self):
        baseline, _ = await self.start()
        for i in range(3):
            self.gateway.succeed(i)
        await self.wait(lambda: baseline.state == "completed")
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
        await self.wait(lambda: first.state == "cancelled")
        self.assertTrue(first.superseded)
        self.assertEqual(first.outcomes[0].status, "succeeded")
        self.gateway = ControlledGateway()
        self.coordinator.gateway = self.gateway
        latest = await self.coordinator.start_run(self.workspace.id, next_request)
        self.store.finish(
            self.workspace.id, self.store.run(self.workspace.id, first.id)
        )
        workspace = self.store.get(self.workspace.id)
        self.assertEqual(workspace.baseline_id, baseline.id)
        self.assertEqual(workspace.latest_id, latest.id)
        self.assertEqual(baseline.outcomes[0].scenario.settings.deployment_cadence, 5)

    async def test_revisions_and_admission(self):
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
        self.assertEqual(status.state, "running")

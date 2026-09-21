import unittest
from uuid import uuid4

import httpx2 as httpx
from tqdm import tqdm

from value_stream.client.web.client import WebSimulationClient
from value_stream.client.web.errors import (
    BatchSimulationError, JobCancelledError, ServiceClientError
)
from value_stream.resources import Developer, QATester, Toolchain
from value_stream.service.codec import encode_result
from value_stream.service.schemas import (
    JobAccepted, JobStatus, ModelError, OutcomeData, OutcomePage
)
from value_stream.simulation import DefaultSimulationPolicy, Model, Simulation
from value_stream.task import Task


def model(cadence=0):
    return Model(
        developer_team=[Developer()], deployment_cadence=cadence,
        qa_testers=QATester.create_pool(limit=1),
        toolchain_pool=Toolchain.create_pool(limit=1, deployment_duration=0.25),
    )


def scripted_client(outcomes, state):
    job_id = uuid4()

    def handle(request):
        if request.method == "POST":
            value = JobAccepted(
                job_id=job_id, status="queued",
                status_url=f"/v1/simulation-jobs/{job_id}",
            )
            return httpx.Response(202, json=value.model_dump(mode="json"))
        if request.url.path.endswith("/outcomes"):
            after = int(request.url.params.get("after", "0"))
            page = OutcomePage(
                outcomes=[outcome for outcome in outcomes if outcome.cursor > after],
                next_cursor=len(outcomes),
            )
            return httpx.Response(200, json=page.model_dump(mode="json"))
        status = JobStatus(
            job_id=job_id, status=state, total_models=len(outcomes),
            queued_models=0, running_models=0,
            succeeded_models=sum(o.status == "succeeded" for o in outcomes),
            failed_models=sum(o.status == "failed" for o in outcomes),
            cancelled_models=sum(o.status == "cancelled" for o in outcomes),
            last_cursor=len(outcomes),
        )
        return httpx.Response(200, json=status.model_dump(mode="json"))

    client = WebSimulationClient("http://test")
    client._http.close()
    client._http = httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://test", trust_env=False
    )
    return client


class Progress(tqdm):
    def __init__(self):
        super().__init__(total=2, disable=True)
        self.count = 0

    def update(self, n=1):
        self.count += 0 if n is None else n


class TestWebClient(unittest.TestCase):
    def test_out_of_order_successes_return_in_submission_order(self):
        tasks = [Task(initial_value=1, story_points=1)]
        models = [model(0), model(1)]
        outcomes = []
        for cursor, index in enumerate((1, 0), start=1):
            result = Simulation().execute(
                model=models[index], tasks=tasks, policy=DefaultSimulationPolicy()
            )
            outcomes.append(OutcomeData(
                cursor=cursor, model_index=index, status="succeeded",
                result=encode_result(result, index),
            ))
        client = scripted_client(outcomes, "completed")
        progress = Progress()
        try:
            results = client.execute(tasks, models, pbar=progress)
        finally:
            client.close()
            progress.close()
        self.assertEqual([result.summary_result.model for result in results], models)
        self.assertEqual(progress.count, 2)

    def test_partial_failure_carries_success_and_indexed_error(self):
        tasks = [Task(initial_value=1, story_points=1)]
        models = [model(0), model(1)]
        success = encode_result(
            Simulation().execute(models[1], tasks, DefaultSimulationPolicy()), 1
        )
        outcomes = [
            OutcomeData(cursor=1, model_index=1, status="succeeded", result=success),
            OutcomeData(
                cursor=2, model_index=0, status="failed",
                error=ModelError(model_index=0, code="MODEL_FAILED", message="bad"),
            ),
        ]
        client = scripted_client(outcomes, "completed_with_errors")
        try:
            with self.assertRaises(BatchSimulationError) as caught:
                client.execute(tasks, models)
        finally:
            client.close()
        self.assertEqual(set(caught.exception.errors), {0})
        self.assertEqual(caught.exception.successful_results[0][0], 1)

    def test_cancelled_job_is_explicit(self):
        tasks = [Task(initial_value=1, story_points=1)]
        client = scripted_client(
            [OutcomeData(cursor=1, model_index=0, status="cancelled")], "cancelled"
        )
        try:
            with self.assertRaises(JobCancelledError):
                client.execute(tasks, [model()])
        finally:
            client.close()

    def test_connection_and_api_errors_are_readable(self):
        tasks = [Task(initial_value=1, story_points=1)]

        def unavailable(_request):
            raise httpx.ConnectError("offline")

        client = WebSimulationClient("http://test")
        client._http.close()
        client._http = httpx.Client(
            transport=httpx.MockTransport(unavailable), base_url="http://test"
        )
        try:
            with self.assertRaisesRegex(ServiceClientError, "connection failed"):
                client.execute(tasks, [model()])
        finally:
            client.close()

        client = WebSimulationClient("http://test")
        client._http.close()
        client._http = httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    429, json={"code": "JOB_CAPACITY", "message": "full"}
                )
            ),
            base_url="http://test",
        )
        try:
            with self.assertRaisesRegex(ServiceClientError, "JOB_CAPACITY: full"):
                client.execute(tasks, [model()])
        finally:
            client.close()

    def test_wait_limit_prevents_endless_polling(self):
        job_id = uuid4()

        def handle(request):
            if request.method == "POST":
                accepted = JobAccepted(
                    job_id=job_id, status="queued",
                    status_url=f"/v1/simulation-jobs/{job_id}",
                )
                return httpx.Response(202, json=accepted.model_dump(mode="json"))
            if request.url.path.endswith("/outcomes"):
                return httpx.Response(
                    200, json=OutcomePage(outcomes=[], next_cursor=0).model_dump(mode="json")
                )
            status = JobStatus(
                job_id=job_id, status="queued", total_models=1,
                queued_models=1, running_models=0, succeeded_models=0,
                failed_models=0, cancelled_models=0, last_cursor=0,
            )
            return httpx.Response(200, json=status.model_dump(mode="json"))

        client = WebSimulationClient(
            "http://test", poll_interval=0.001, max_wait_seconds=0.01
        )
        client._http.close()
        client._http = httpx.Client(
            transport=httpx.MockTransport(handle), base_url="http://test"
        )
        try:
            with self.assertRaisesRegex(ServiceClientError, "wait limit"):
                client.execute([Task(initial_value=1, story_points=1)], [model()])
        finally:
            client.close()

    def test_malformed_success_outcome_cannot_be_silently_dropped(self):
        job_id = uuid4()

        def handle(request):
            if request.method == "POST":
                return httpx.Response(202, json={
                    "job_id": str(job_id), "status": "queued",
                    "status_url": f"/v1/simulation-jobs/{job_id}",
                })
            if request.url.path.endswith("/outcomes"):
                return httpx.Response(200, json={
                    "outcomes": [{
                        "cursor": 1, "model_index": 0, "status": "succeeded",
                        "result": None, "error": None,
                    }],
                    "next_cursor": 1,
                })
            return httpx.Response(200, json={
                "job_id": str(job_id), "status": "completed", "total_models": 1,
                "queued_models": 0, "running_models": 0, "succeeded_models": 1,
                "failed_models": 0, "cancelled_models": 0, "last_cursor": 1,
            })

        client = WebSimulationClient("http://test")
        client._http.close()
        client._http = httpx.Client(
            transport=httpx.MockTransport(handle), base_url="http://test"
        )
        try:
            with self.assertRaisesRegex(ServiceClientError, "malformed outcomes"):
                client.execute([Task(initial_value=1, story_points=1)], [model()])
        finally:
            client.close()

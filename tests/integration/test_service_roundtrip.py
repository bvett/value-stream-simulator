import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from value_stream.service.app import create_app
from value_stream.service.schemas import JobState, JobStatus
from value_stream.service.settings import ServiceSettings


def wait_for_status(
    client: TestClient,
    job_id: str,
    terminal_states: tuple[JobState, ...],
    timeout_seconds: float = 5,
) -> JobStatus:
    deadline = time.monotonic() + timeout_seconds
    status = JobStatus.model_validate(
        client.get(f"/v1/simulation-jobs/{job_id}").json()
    )
    while status.status not in terminal_states and time.monotonic() < deadline:
        time.sleep(0.05)
        status = JobStatus.model_validate(
            client.get(f"/v1/simulation-jobs/{job_id}").json()
        )
    return status


def model(cadence: int = 0, failure_rate: float = 0.0):
    return {
        "developer_team": [{"name": "Dev", "efficiency": 1}],
        "deployment_cadence": cadence,
        "qa_testers": {
            "kind": "pool", "limit": 1, "time_cost": 0.1,
            "failure_rate": 0, "failure_cost": 0,
        },
        "toolchain_pool": {
            "kind": "pool", "limit": 1,
            "deployment_duration": 0.25, "failure_rate": failure_rate,
        },
        "support_interval": None,
        "support_task_story_points": 1,
    }


def request(models=None, seed=123):
    return {
        "tasks": [{
            "initial_value": 1, "story_points": 1,
            "depreciation_rate": 0.005, "task_name": "A",
            "creation_sim_t": 0, "task_type": "development",
        }],
        "models": models or [model()],
        "seed": seed,
    }


class TestServiceRoundTrip(unittest.TestCase):
    def test_batch_outcomes(self):
        settings = ServiceSettings(max_model_seconds=10)
        with TestClient(create_app(settings)) as client:
            submitted = client.post(
                "/v1/simulation-jobs", json=request([model(0), model(1)])
            )
            self.assertEqual(submitted.status_code, 202, submitted.text)
            job_id = submitted.json()["job_id"]
            status = wait_for_status(
                client, job_id, ("completed", "completed_with_errors"), 10
            )
            self.assertEqual(status.status, "completed", status)
            page = client.get(
                f"/v1/simulation-jobs/{job_id}/outcomes?after=0"
            ).json()
            self.assertEqual({item["model_index"] for item in page["outcomes"]}, {0, 1})
            self.assertEqual(len(page["outcomes"]), 2)
            self.assertEqual(
                client.get(
                    f"/v1/simulation-jobs/{job_id}/outcomes?after={page['next_cursor']}"
                ).json()["outcomes"],
                [],
            )

    def test_openapi_and_validation(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/openapi.json").json()["openapi"], "3.1.0")
            bad = request()
            bad["models"][0]["developer_team"] = []
            response = client.post("/v1/simulation-jobs", json=bad)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["code"], "INVALID_INPUT")

    def test_model_failure_does_not_stop_batch(self):
        settings = ServiceSettings(max_model_seconds=1)
        with TestClient(create_app(settings)) as client:
            submitted = client.post(
                "/v1/simulation-jobs",
                json=request([model(0, failure_rate=1), model(1)], seed=5),
            )
            self.assertEqual(submitted.status_code, 202)
            job_id = submitted.json()["job_id"]
            status = wait_for_status(
                client, job_id, ("completed", "completed_with_errors")
            )
            self.assertEqual(status.status, "completed_with_errors", status)
            outcomes = client.get(f"/v1/simulation-jobs/{job_id}/outcomes").json()[
                "outcomes"
            ]
            by_index = {item["model_index"]: item for item in outcomes}
            self.assertEqual(by_index[0]["status"], "failed")
            self.assertEqual(by_index[0]["error"]["model_index"], 0)
            self.assertEqual(by_index[1]["status"], "succeeded")

    def test_seeded_summary_repeats(self):
        with TestClient(create_app()) as client:
            summaries = []
            for _ in range(2):
                submitted = client.post(
                    "/v1/simulation-jobs",
                    json=request([model(0, failure_rate=0.4)], seed=99),
                )
                job_id = submitted.json()["job_id"]
                status = wait_for_status(client, job_id, ("completed",))
                self.assertEqual(status.status, "completed", status)
                result = client.get(
                    f"/v1/simulation-jobs/{job_id}/outcomes"
                ).json()["outcomes"][0]["result"]
                summaries.append(result["summary_result"])
            self.assertEqual(summaries[0], summaries[1])

    def test_body_and_count_limits(self):
        settings = ServiceSettings(max_body_bytes=100, max_models=1)
        with TestClient(create_app(settings)) as client:
            oversized = client.post("/v1/simulation-jobs", json=request())
            self.assertEqual(oversized.status_code, 413)
            self.assertEqual(oversized.json()["code"], "BODY_TOO_LARGE")
            streamed = client.post(
                "/v1/simulation-jobs",
                content=(chunk for chunk in (b"x" * 60, b"x" * 60)),
                headers={"content-type": "application/json"},
            )
            self.assertEqual(streamed.status_code, 413)
            self.assertEqual(streamed.json()["code"], "BODY_TOO_LARGE")
        with TestClient(create_app(ServiceSettings(max_models=1))) as client:
            too_many = client.post(
                "/v1/simulation-jobs", json=request([model(0), model(1)])
            )
            self.assertEqual(too_many.status_code, 422)
            self.assertEqual(too_many.json()["code"], "LIMIT_EXCEEDED")

    def test_cancellation_is_readable(self):
        with TestClient(create_app(ServiceSettings(max_model_seconds=5))) as client:
            submitted = client.post(
                "/v1/simulation-jobs", json=request([model(failure_rate=1)])
            )
            job_id = submitted.json()["job_id"]
            response = client.delete(f"/v1/simulation-jobs/{job_id}")
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "cancelled")
            page = client.get(f"/v1/simulation-jobs/{job_id}/outcomes").json()
            self.assertEqual(page["outcomes"][0]["status"], "cancelled")

    def test_result_size_limit_becomes_model_error(self):
        settings = ServiceSettings(max_model_outcome_bytes=1)
        with TestClient(create_app(settings)) as client:
            submitted = client.post("/v1/simulation-jobs", json=request())
            job_id = submitted.json()["job_id"]
            status = wait_for_status(client, job_id, ("completed_with_errors",))
            self.assertEqual(status.status, "completed_with_errors", status)
            outcome = client.get(
                f"/v1/simulation-jobs/{job_id}/outcomes"
            ).json()["outcomes"][0]
            self.assertEqual(outcome["error"]["code"], "RESULT_TOO_LARGE")

    def test_model_timeout_reclaims_worker_slot(self):
        settings = ServiceSettings(max_model_workers=1, max_model_seconds=0.000001)
        with TestClient(create_app(settings)) as client:
            submitted = client.post(
                "/v1/simulation-jobs", json=request([model(0), model(1)])
            )
            job_id = submitted.json()["job_id"]
            status = wait_for_status(client, job_id, ("completed_with_errors",))
            self.assertEqual(status.status, "completed_with_errors", status)
            outcomes = client.get(f"/v1/simulation-jobs/{job_id}/outcomes").json()[
                "outcomes"
            ]
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(
                {item["error"]["code"] for item in outcomes}, {"MODEL_TIMEOUT"}
            )

    def test_active_job_limit_queues_next_job(self):
        settings = ServiceSettings(
            max_active_jobs=1, max_queued_jobs=1,
            max_model_workers=1, max_model_seconds=1,
        )
        with TestClient(create_app(settings)) as client:
            first = client.post(
                "/v1/simulation-jobs", json=request([model(failure_rate=1)])
            ).json()["job_id"]
            second = client.post(
                "/v1/simulation-jobs", json=request([model(0)])
            ).json()["job_id"]
            self.assertEqual(
                client.get(f"/v1/simulation-jobs/{second}").json()["status"],
                "queued",
            )
            self.assertEqual(
                client.post("/v1/simulation-jobs", json=request()).status_code,
                429,
            )
            second_status = wait_for_status(
                client, second, ("completed", "completed_with_errors")
            ).status
            self.assertEqual(second_status, "completed")

    def test_unexpected_submission_error_has_documented_envelope(self):
        application = create_app()
        with TestClient(application, raise_server_exceptions=False) as client:
            with patch.object(
                application.state.scheduler, "submit", side_effect=RuntimeError("boom")
            ):
                response = client.post("/v1/simulation-jobs", json=request())
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["code"], "INTERNAL_ERROR")
            self.assertNotIn("boom", response.text)

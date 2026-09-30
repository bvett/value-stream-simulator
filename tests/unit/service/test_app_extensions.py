import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError
from fastapi.testclient import TestClient
from unittest.mock import patch
from value_stream.service.app import create_app
from value_stream.service.schemas import JobRequest
from value_stream.service.job_store import InMemoryJobStore, SubmissionConflict
from value_stream.service.settings import ServiceSettings
from value_stream.service.worker import run


class TestApplicationExtensions(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(Path("tests/fixtures/service_job.json").read_text())

    def test_seed_validation(self):
        self.payload["model_seeds"] = []
        with self.assertRaises(ValidationError):
            JobRequest.model_validate(self.payload)
        self.payload["model_seeds"] = [-1] * len(self.payload["models"])
        with self.assertRaises(ValidationError):
            JobRequest.model_validate(self.payload)

    def test_atomic_idempotency(self):
        store = InMemoryJobStore(ServiceSettings())
        key = uuid4()
        with ThreadPoolExecutor(8) as executor:
            results = list(
                executor.map(lambda _: store.reserve(1, key, "same"), range(20))
            )
        self.assertEqual(len({r[0] for r in results}), 1)
        self.assertEqual(sum(r[1] for r in results), 1)
        with self.assertRaises(SubmissionConflict):
            store.reserve(1, key, "different")

    def test_http_retry_schedules_once(self):
        app = create_app()
        self.payload["submission_id"] = str(uuid4())
        with (
            TestClient(app) as client,
            patch.object(app.state.scheduler, "submit") as submit,
        ):
            a = client.post("/v1/simulation-jobs", json=self.payload)
            b = client.post("/v1/simulation-jobs", json=self.payload)
            self.assertEqual(a.json()["job_id"], b.json()["job_id"])
            self.assertEqual(submit.call_count, 1)
            self.payload["tasks"][0]["story_points"] += 1
            self.assertEqual(
                client.post("/v1/simulation-jobs", json=self.payload).status_code, 409
            )

    def test_explicit_seed_independent_of_index_with_support(self):
        model = self.payload["models"][0]
        model["developer_team"] = [
            {"name": str(i), "efficiency": 0.5 + i} for i in range(3)
        ]
        model["support_interval"] = 2
        model["support_task_story_points"] = 0.2
        model["qa_testers"]["failure_rate"] = 0.2
        model["qa_testers"]["failure_cost"] = 0.2
        request = {
            "tasks": self.payload["tasks"] * 8,
            "models": [model],
            "model_seeds": [745],
        }

        def normalize(result):
            result.pop("model_index")
            for event in result["metadata"]["event_metadata"]:
                event.pop("resource_id", None)
            return result

        first = normalize(run({"model_index": 0, "request": request})["result"])
        for index in [3, 0, 7]:
            self.assertEqual(
                first,
                normalize(run({"model_index": index, "request": request})["result"]),
            )

import asyncio
import csv
import io
import unittest
from uuid import uuid4
from dataclasses import replace
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from value_stream.app.errors import AppError
from value_stream.app.settings import AppSettings
from value_stream.app.storage import InMemoryWorkspaceStore
from value_stream.app.schemas import (
    EditorRequest,
    TaskSetSpec,
    ScenarioDefinition,
    RunRequest,
    ModelSettings,
    RunStatus,
)
from value_stream.app.server import create_app
from value_stream.app.gateway import HttpSimulationGateway
from value_stream.app.generation import expand_scenarios
from value_stream.app.metrics import plot_data
from value_stream.service.schemas import (
    ResultData,
    SummaryData,
    MetadataData,
    ResourceMetadataData,
)


class TestStorageLimits(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryWorkspaceStore(
            AppSettings(
                max_workspaces=1,
                max_pins=1,
                max_resources=5,
                max_retained_runs=3,
                min_interactive_seconds=0.001,
            )
        )
        self.w = self.store.create()
        self.preview = self.store.save_editor(
            self.w.id,
            EditorRequest(
                expected_revision=0,
                task_spec=TaskSetSpec(count=1),
                definitions=[ScenarioDefinition()],
            ),
        )
        self.w = self.store.get(self.w.id)
        self.task_set = self.w.task_sets[0]

    def record(self):
        return self.store.register(
            self.w.id,
            RunRequest(request_id=uuid4(), preview_digest=self.preview.digest),
            self.preview.scenarios,
            self.task_set,
        )[0]

    def complete(self, record):
        result = ResultData(
            model_index=0,
            model=self.preview.scenarios[0].model,
            summary_result=SummaryData(
                completion_time=1, loss=-0.5, total_delivered_value=0.5
            ),
            metadata=MetadataData(event_metadata=[], resource_metadata=[]),
        )
        self.store.retain_result(record, 0, result)
        record.status.outcomes[0].status = "succeeded"
        record.status.state = "completed"
        self.store.finish(self.w.id, record)

    def test_pin_history_delete_and_capacity(self):
        with self.assertRaises(AppError):
            self.store.create()
        first = self.record()
        with self.assertRaises(AppError):
            self.store.delete_workspace(self.w.id)
        with self.assertRaises(AppError):
            self.store.comparison(self.w.id, first.status.id, "pin")
        self.complete(first)
        self.store.comparison(self.w.id, first.status.id, "pin")
        second = self.record()
        self.complete(second)
        with self.assertRaisesRegex(AppError, "Unpin"):
            self.store.comparison(self.w.id, second.status.id, "pin")
        self.store.comparison(self.w.id, first.status.id, "unpin")
        self.store.comparison(self.w.id, second.status.id, "pin")
        self.store.comparison(self.w.id, second.status.id, "baseline")
        self.store.comparison(self.w.id, first.status.id, "delete")
        self.assertTrue(
            self.store.result(second, second.status.outcomes[0].scenario.id)
        )
        self.store.delete_workspace(self.w.id)
        self.assertEqual(len(self.store.cache), 0)
        with self.assertRaises(AppError):
            self.store.get(self.w.id)

    def test_result_budget_and_protected_retention(self):
        self.store.settings = replace(
            self.store.settings,
            max_model_bytes=10,
            max_run_bytes=10,
            max_result_bytes=10,
        )
        record = self.record()
        with self.assertRaisesRegex(AppError, "storage limit"):
            self.complete(record)
        record.status.state = "failed"
        self.store.finish(self.w.id, record)
        self.assertEqual(record.reservation, 0)

    def test_task_set_reuse_deletion_and_model_resource_limit(self):
        request = EditorRequest(
            expected_revision=1,
            task_spec=TaskSetSpec(count=2),
            definitions=[ScenarioDefinition()],
        )
        self.store.save_editor(self.w.id, request)
        self.store.delete_task_set(self.w.id, self.task_set.id, 2)
        self.assertEqual(len(self.store.get(self.w.id).task_sets), 1)
        with self.assertRaises(AppError):
            self.store.delete_task_set(self.w.id, self.task_set.id, 3)
        with self.assertRaises(AppError):
            expand_scenarios(
                [ScenarioDefinition(settings=ModelSettings(team_size=6))],
                self.store.settings,
            )

    def test_input_budget_and_missing_objects(self):
        self.store.settings = replace(self.store.settings, max_input_bytes=1)
        with self.assertRaisesRegex(AppError, "Input storage"):
            self.store.save_editor(
                self.w.id,
                EditorRequest(
                    expected_revision=1,
                    task_spec=TaskSetSpec(),
                    definitions=[ScenarioDefinition()],
                ),
            )
        self.assertEqual(self.store.get(self.w.id).revision, 1)
        with self.assertRaises(AppError):
            self.store.run(self.w.id, uuid4())
        with self.assertRaises(AppError):
            self.store.get(uuid4())

    def test_settings_environment(self):
        with patch.dict(
            "os.environ",
            {
                "VALUE_STREAM_APP_MAX_MODELS": "12",
                "VALUE_STREAM_APP_POLL_SECONDS": "0.02",
            },
        ):
            settings = AppSettings.from_environment()
            self.assertEqual(settings.max_models, 12)
            self.assertEqual(settings.poll_seconds, 0.02)
        with self.assertRaises(ValueError):
            AppSettings(max_models=0)
        with self.assertRaises(ValueError):
            AppSettings(poll_seconds=float("nan"))


class TestGateway(unittest.IsolatedAsyncioTestCase):
    async def gateway(self, handler, limit=10000):
        gateway = HttpSimulationGateway("http://fixture", limit)
        gateway.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://fixture"
        )
        self.addAsyncCleanup(gateway.close)
        return gateway

    async def test_compatibility_and_errors(self):
        gateway = await self.gateway(
            lambda r: httpx.Response(200, json={"status": "ok"})
        )
        with self.assertRaisesRegex(AppError, "Update the simulation service"):
            await gateway.ready()
        gateway2 = await self.gateway(
            lambda r: httpx.Response(
                429, json={"code": "JOB_CAPACITY", "message": "full"}
            )
        )
        with self.assertRaisesRegex(AppError, "full"):
            await gateway2.status(uuid4())

    async def test_bounded_body_invalid_json_disconnect_and_close(self):
        huge = await self.gateway(
            lambda r: httpx.Response(200, content=b"x" * 100), limit=20
        )
        with self.assertRaisesRegex(AppError, "exceeds"):
            await huge.request("GET", "/")
        invalid = await self.gateway(lambda r: httpx.Response(200, content="not json"))
        with self.assertRaisesRegex(AppError, "invalid JSON"):
            await invalid.request("GET", "/")

        non_object = await self.gateway(lambda r: httpx.Response(500, json=[]))
        with self.assertRaisesRegex(AppError, "non-object"):
            await non_object.request("GET", "/")

        def disconnected(request):
            raise httpx.ConnectError("offline")

        offline = await self.gateway(disconnected)
        with self.assertRaisesRegex(AppError, "Cannot reach"):
            await offline.status(uuid4())
        await offline.close()
        with self.assertRaisesRegex(AppError, "not connected"):
            await offline.status(uuid4())


class NoService:
    async def start(self):
        pass

    async def close(self):
        pass

    async def ready(self):
        raise AppError("SERVICE_UNAVAILABLE", "offline", 503)


class TestAppErrors(unittest.TestCase):
    def test_request_errors_config_and_static_separation(self):
        app = create_app(settings=AppSettings(max_body_bytes=1000), gateway=NoService())
        with TestClient(app) as client:
            self.assertFalse(client.get("/api/v1/config").json()["ready"])
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 503)
            self.assertEqual(client.get("/api/v1/missing").status_code, 404)
            w = client.post("/api/v1/workspaces").json()
            path = "/api/v1/workspaces/" + w["id"]
            self.assertEqual(
                client.put(path + "/editor", content="x" * 1001).status_code, 413
            )
            invalid = client.put(path + "/editor", json={})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["code"], "INVALID_INPUT")
            self.assertEqual(
                client.get(path + "/runs/" + str(uuid4())).status_code, 404
            )
            self.assertEqual(client.delete(path).status_code, 204)

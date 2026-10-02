"""Production HTTP gateway roundtrip, including workspace retention."""

import csv
import io
import json
import time
import unittest
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from jsondiff import JsonDiffer
from value_stream.app.server import create_app
from value_stream.app.settings import AppSettings


class TestAppRoundtrip(unittest.TestCase):
    def test_local_service_browser_contract_and_retention(self):
        app = create_app(
            settings=AppSettings(poll_seconds=0.01, min_interactive_seconds=0.01)
        )
        with TestClient(app) as client:
            self.assertEqual(client.get("/ready").status_code, 200)
            w = client.post("/api/v1/workspaces").json()
            path = "/api/v1/workspaces/" + w["id"]
            spec = w["task_spec"]
            spec["count"] = 5
            request = {
                "expected_revision": w["revision"],
                "task_spec": spec,
                "definitions": w["definitions"],
            }
            preview = client.put(path + "/editor", json=request).json()
            self.assertEqual(preview["count"], 9)
            payload = {
                "request_id": str(uuid4()),
                "preview_digest": preview["digest"],
                "name": "First comparison",
            }
            response = client.post(path + "/runs", json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            run_id = response.json()["id"]
            deadline = time.monotonic() + 20
            run = None
            while time.monotonic() < deadline:
                run = client.get(path + "/runs/" + run_id).json()
                if run["state"] in {"completed", "failed", "completed_with_errors"}:
                    break
                time.sleep(0.03)
            assert run is not None
            self.assertEqual(run["state"], "completed", run)
            self.assertEqual(len(run["outcomes"]), 9)
            self.assertEqual(
                client.post(path + "/runs", json=payload).json()["id"], run_id
            )
            result_path = (
                f"{path}/runs/{run_id}/results/{run['outcomes'][0]['scenario']['id']}"
            )
            self.assertEqual(client.get(result_path).status_code, 200)
            for kind in ["summary", "events", "resources"]:
                export = client.get(f"{path}/runs/{run_id}/exports/{kind}")
                self.assertEqual(export.status_code, 200)
                rows = list(csv.DictReader(io.StringIO(export.text)))
                self.assertTrue(rows)
            # App-owned retained results remain readable after upstream state is gone.
            self.assertEqual(client.get(path).json()["baseline_id"], run_id)
            assert client.portal is not None
            client.portal.call(app.state.gateway.close)
            self.assertEqual(client.get("/ready").status_code, 503)
            self.assertEqual(client.get(result_path).status_code, 200)
            self.assertEqual(
                client.put(path + "/editor", json=request).status_code, 409
            )
            invalid = {**payload, "request_id": str(uuid4()), "preview_digest": "stale"}
            self.assertEqual(client.post(path + "/runs", json=invalid).status_code, 409)

    def test_external_service_survives_app_shutdown(self):
        import httpx
        from value_stream.client.web.local_service import (
            acquire_local_service,
            release_local_service,
        )

        url = acquire_local_service()
        try:
            with TestClient(create_app(service_url=url)) as client:
                self.assertEqual(client.get("/ready").status_code, 200)
            with httpx.Client(trust_env=False) as client:
                self.assertEqual(client.get(url + "/health").status_code, 200)
        finally:
            release_local_service()

    def test_contract_snapshot(self):
        exclude_paths = ['paths./ready.get.responses.413.description',
                         'paths./ready.get.responses.422.description',
                         'paths./api/v1/workspaces.post.responses.413.description',
                         'paths./api/v1/workspaces.post.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}.get.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}.get.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}.delete.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}.delete.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/editor.put.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/editor.put.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/preview.post.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/preview.post.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/task-sets/{task_set_id}.delete.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/task-sets/{task_set_id}.delete.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs.post.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs.post.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}.get.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}.get.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}.delete.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}.delete.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/outcomes.get.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/outcomes.get.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/resume.post.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/resume.post.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/comparison.post.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/comparison.post.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/results/{scenario_id}.get.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/results/{scenario_id}.get.responses.422.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/exports/{kind}.get.responses.413.description',
                         'paths./api/v1/workspaces/{workspace_id}/runs/{run_id}/exports/{kind}.get.responses.422.description',
                         ]

        
        diff = JsonDiffer().diff(json.loads(Path("src/value_stream/app/openapi.json").read_text()), 
                                 create_app().openapi(), exclude_paths=exclude_paths)
        self.assertEqual(diff, {})

"""Single-origin web application and JSON contract."""

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional
from uuid import UUID
from fastapi import FastAPI, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Scope, Receive, Send
from pydantic import ValidationError
from value_stream.service.schemas import ErrorEnvelope, HealthResponse
from .settings import AppSettings
from .storage import InMemoryWorkspaceStore, WorkspaceStore
from .gateway import HttpSimulationGateway
from .coordinator import RunCoordinator
from .errors import AppError
from .schemas import (
    Workspace,
    EditorRequest,
    Preview,
    RunRequest,
    RunStatus,
    OutcomeSummary,
    ComparisonMutation,
    ResultView,
    AppConfig,
    TERMINAL,
)
from .metrics import plot_data
from .insights import observations
from .exports import export_csv

logger = logging.getLogger(__name__)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        size, messages = 0, []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse(
                    AppError(
                        "BODY_TOO_LARGE",
                        "Request exceeds the configured body limit",
                        413,
                    ).body(),
                    status_code=413,
                )(scope, receive, send)
            messages.append(message)
            if not message.get("more_body"):
                break
        iterator = iter(messages)

        async def replay():
            return next(iterator)

        await self.app(scope, replay, send)


def create_app(settings : Optional[AppSettings]=None, store : Optional[WorkspaceStore]=None, gateway=None, service_url=None):
    settings = settings or AppSettings.from_environment()
    store = store or InMemoryWorkspaceStore(settings)
    gateway = gateway or HttpSimulationGateway(
        service_url or os.getenv("VALUE_STREAM_SERVICE_URL"),
        settings.max_run_bytes + 1024 * 1024,
    )
    coordinator = RunCoordinator(store, gateway)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await gateway.start()
        except Exception:
            logger.exception(
                "Simulation service startup failed; workspace UI remains available"
            )
        yield
        await coordinator.close()
        await gateway.close()

    app = FastAPI(title="Value Stream Application", version="1.0.0", lifespan=lifespan)
    app.state.store, app.state.coordinator, app.state.gateway = (
        store,
        coordinator,
        gateway,
    )
    app.add_middleware(BodyLimitMiddleware, limit=settings.max_body_bytes)

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid(request, exc):
        issues = [
            {"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            AppError(
                "INVALID_INPUT",
                "Please correct the highlighted inputs.",
                details={"issues": issues},
            ).body(),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.exception("Unexpected application error", exc_info=exc)
        return JSONResponse(
            AppError("INTERNAL_ERROR", "Unexpected application error", 500).body(),
            status_code=500,
        )

    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ErrorEnvelope}
        for code in [404, 409, 413, 422, 429, 500, 502, 503]
    }
    prefix = "/api/v1/workspaces/{workspace_id}"

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse()

    @app.get("/ready", response_model=HealthResponse, responses=errors)
    async def ready():
        await gateway.ready()
        return HealthResponse()

    @app.get("/api/v1/config", response_model=AppConfig)
    async def config():
        try:
            await gateway.ready()
            return AppConfig(limits=asdict(settings), ready=True)
        except AppError as exc:
            return AppConfig(
                limits=asdict(settings), ready=False, error=ErrorEnvelope(**exc.body())
            )

    @app.post(
        "/api/v1/workspaces",
        response_model=Workspace,
        status_code=201,
        responses=errors,
    )
    async def create_workspace():
        return store.create()

    @app.get(prefix, response_model=Workspace, responses=errors)
    async def workspace(workspace_id: UUID):
        return store.get(workspace_id)

    @app.delete(prefix, status_code=204, responses=errors)
    async def delete_workspace(workspace_id: UUID):
        store.delete_workspace(workspace_id)

    @app.put(prefix + "/editor", response_model=Preview, responses=errors)
    async def save_editor(workspace_id: UUID, request: EditorRequest):
        return store.save_editor(workspace_id, request)

    @app.post(prefix + "/preview", response_model=Preview, responses=errors)
    async def preview(workspace_id: UUID):
        return store.preview(workspace_id)

    @app.delete(prefix + "/task-sets/{task_set_id}", status_code=204, responses=errors)
    async def delete_task_set(
        workspace_id: UUID, task_set_id: UUID, expected_revision: int
    ):
        store.delete_task_set(workspace_id, task_set_id, expected_revision)

    @app.post(
        prefix + "/runs", response_model=RunStatus, status_code=202, responses=errors
    )
    async def start_run(workspace_id: UUID, request: RunRequest):
        return await coordinator.start_run(workspace_id, request)

    @app.get(prefix + "/runs/{run_id}", response_model=RunStatus, responses=errors)
    async def run(workspace_id: UUID, run_id: UUID):
        return store.run(workspace_id, run_id).status

    @app.get(
        prefix + "/runs/{run_id}/outcomes",
        response_model=list[OutcomeSummary],
        responses=errors,
    )
    async def outcomes(workspace_id: UUID, run_id: UUID, after: int = Query(0, ge=0)):
        return sorted(
            [
                o
                for o in store.run(workspace_id, run_id).status.outcomes
                if o.cursor > after
            ],
            key=lambda o: o.cursor,
        )

    @app.delete(
        prefix + "/runs/{run_id}",
        response_model=RunStatus,
        status_code=202,
        responses=errors,
    )
    async def cancel(workspace_id: UUID, run_id: UUID):
        return await coordinator.cancel_run(workspace_id, run_id)

    @app.post(
        prefix + "/runs/{run_id}/resume", response_model=RunStatus, responses=errors
    )
    async def resume(workspace_id: UUID, run_id: UUID):
        return coordinator.resume(workspace_id, run_id)

    @app.post(
        prefix + "/runs/{run_id}/comparison", response_model=Workspace, responses=errors
    )
    async def comparison(
        workspace_id: UUID, run_id: UUID, mutation: ComparisonMutation
    ):
        return store.comparison(workspace_id, run_id, mutation.action)

    @app.get(
        prefix + "/runs/{run_id}/results/{scenario_id}",
        response_model=ResultView,
        responses=errors,
    )
    async def result(workspace_id: UUID, run_id: UUID, scenario_id: UUID):
        record = store.run(workspace_id, run_id)
        result = store.result(record, scenario_id)
        scenario = next(
            o.scenario for o in record.status.outcomes if o.scenario.id == scenario_id
        )
        metrics = plot_data(result, sum(t.initial_value for t in record.task_set.tasks))
        insights = [
            o
            for o in observations(metrics, scenario.settings)
            if o.property not in {"qa_size", "team_size", "toolchain_size"}
            or ((o.value is not None) and (int(o.value) <= settings.max_resources))
        ]
        return ResultView(
            scenario_id=scenario_id, metrics=metrics, observations=insights
        )

    @app.get(
        prefix + "/runs/{run_id}/exports/{kind}",
        responses={200: {"content": {"text/csv": {}}}, **errors},
    )
    async def export(workspace_id: UUID, run_id: UUID, kind: str):
        if kind not in {"summary", "events", "resources"}:
            raise AppError("INVALID_INPUT", "Choose summary, events, or resources")
        record = store.run(workspace_id, run_id)
        if record.status.state not in TERMINAL:
            raise AppError(
                "RUN_ACTIVE",
                "Wait for completion or cancel before exporting a stable comparison",
                409,
            )
        # Snapshot both rows and result references before streaming across threads.
        import copy

        snapshot = copy.copy(record)
        snapshot.status = record.status.model_copy(deep=True)
        frozen_results = {sid: store.result(record, sid) for sid in record.results}

        class ExportStore:
            def result(self, record, sid):
                return frozen_results[sid]

        return StreamingResponse(
            export_csv(ExportStore(), snapshot, kind),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{kind}-{run_id}.csv"'
            },
        )

    class CachedAssets(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            return response

    static = Path(__file__).parent / "static"
    if (static / "assets").exists():
        app.mount("/assets", CachedAssets(directory=static / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        if not (static / "index.html").is_file():
            return JSONResponse(
                {
                    "code": "ASSETS_MISSING",
                    "message": "Build the UI: npm run build --prefix src/value_stream/app/frontend",
                },
                status_code=503,
            )
        return FileResponse(
            static / "index.html", headers={"Cache-Control": "no-cache"}
        )

    return app

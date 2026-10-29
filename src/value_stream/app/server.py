"""Single-origin web application and JSON contract."""

import copy
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import UUID
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from pydantic import ValidationError
from value_stream.service.schemas import ErrorEnvelope, HealthResponse, ResultData
from value_stream.service.persistence.config import DatabaseConfig, ensure_distinct_databases
from .settings import AppSettings
from .examples import available_examples
from .storage import WorkspaceStore, RunRecord
from .sqlite_storage import SqliteWorkspaceStore
from .gateway import HttpSimulationGateway, SimulationGateway
from .coordinator import RunCoordinator
from .errors import AppError
from .schemas import (
    Workspace,
    ExampleCatalog,
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
    """Rejects requests whose bodies exceed the configured size limit."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        size = 0
        messages: list[Message] = []
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

        async def replay() -> Message:
            return next(iterator)

        await self.app(scope, replay, send)


def create_app(
    settings: AppSettings | None = None,
    store: WorkspaceStore | None = None,
    gateway: SimulationGateway | None = None,
    service_url: str | None = None,
    database: str | Path | None = None,
    data_dir: str | Path | None = None,
    service_database: str | Path | None = None,
) -> FastAPI:
    """Build routes without acquiring database, network, or scheduler resources.

    Args:
        settings: Application limits.
        store: Optional injected store, owned and closed during lifespan.
        gateway: Optional injected simulation boundary.
        service_url: External endpoint, otherwise use an owned-local service.
        database: Explicit application database filename.
        data_dir: Directory containing default application/service databases.
        service_database: Explicit owned-local simulation database filename.
    """
    settings = settings or AppSettings.from_environment()
    configured_url = (
        service_url if service_url is not None else os.getenv("VALUE_STREAM_SERVICE_URL")
    )
    if configured_url and service_database is not None:
        raise ValueError("A service database cannot configure an external service")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        opened: WorkspaceStore | None = None
        connected: SimulationGateway | None = None
        coordinator: RunCoordinator | None = None
        try:
            config = (
                None
                if store is not None
                else DatabaseConfig.resolve("application", database=database, data_dir=data_dir)
            )
            connected = (
                gateway
                if gateway is not None
                else HttpSimulationGateway(
                    configured_url,
                    settings.max_run_bytes + 1024 * 1024,
                    database=service_database,
                    data_dir=data_dir,
                )
            )
            if isinstance(connected, HttpSimulationGateway) and connected.kind == "local":
                _ = connected.identity
                owned_config = config
                if owned_config is None and isinstance(store, SqliteWorkspaceStore):
                    owned_config = store.database.config
                if owned_config is not None and connected.local_config is not None:
                    ensure_distinct_databases(owned_config, connected.local_config)
            if store is not None:
                opened = store
            else:
                assert config is not None
                opened = SqliteWorkspaceStore(config, settings)
            app.state.store, app.state.gateway = opened, connected
            if isinstance(connected, HttpSimulationGateway):
                coordinator = RunCoordinator(
                    opened,
                    connected,
                    upstream_kind=connected.kind,
                    upstream_identity=connected.identity,
                )
            else:
                coordinator = RunCoordinator(opened, connected)
            app.state.coordinator = coordinator
            try:
                await connected.start()
            except Exception:
                logger.exception(
                    "Simulation service startup failed; retained workspace data remains available"
                )
            coordinator.recover()
            yield
        finally:
            try:
                if coordinator is not None:
                    await coordinator.close()
            finally:
                try:
                    if connected is not None:
                        await connected.close()
                finally:
                    if opened is not None:
                        opened.close()

    app = FastAPI(title="Value Stream Application", version="1.0.0", lifespan=lifespan)
    app.state.store, app.state.gateway, app.state.coordinator = store, gateway, None

    def current_store() -> WorkspaceStore:
        """Resolve storage initialized by the active lifespan."""
        return app.state.store

    def current_gateway() -> SimulationGateway:
        """Resolve the configured gateway, including startup readiness failures."""
        return app.state.gateway

    def current_coordinator() -> RunCoordinator:
        """Resolve the coordinator initialized after opening the workspace store."""
        return app.state.coordinator

    app.add_middleware(BodyLimitMiddleware, limit=settings.max_body_bytes)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid(
        request: Request, exc: RequestValidationError | ValidationError
    ) -> JSONResponse:
        issues = [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            AppError(
                "INVALID_INPUT",
                "Please correct the highlighted inputs.",
                details={"issues": issues},
            ).body(),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected application error", exc_info=exc)
        return JSONResponse(
            AppError("INTERNAL_ERROR", "Unexpected application error", 500).body(),
            status_code=500,
        )

    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ErrorEnvelope} for code in [404, 409, 413, 422, 429, 500, 502, 503]
    }
    prefix = "/api/v1/workspaces/{workspace_id}"

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/ready", response_model=HealthResponse, responses=errors)
    async def ready() -> HealthResponse:
        await current_gateway().ready()
        return HealthResponse()

    @app.get("/api/v1/config", response_model=AppConfig)
    async def config() -> AppConfig:
        try:
            await current_gateway().ready()
            return AppConfig(limits=asdict(settings), ready=True)
        except AppError as exc:
            return AppConfig(
                limits=asdict(settings), ready=False, error=ErrorEnvelope(**exc.body())
            )

    @app.get("/api/v1/examples", response_model=ExampleCatalog)
    async def examples() -> ExampleCatalog:
        """List documentation views whose saved data has not been deleted."""
        return available_examples(current_store())

    @app.post(
        "/api/v1/workspaces",
        response_model=Workspace,
        status_code=201,
        responses=errors,
    )
    async def create_workspace() -> Workspace:
        return current_store().create()

    @app.get(prefix, response_model=Workspace, responses=errors)
    async def workspace(workspace_id: UUID) -> Workspace:
        return current_store().get(workspace_id)

    @app.delete(prefix, status_code=204, responses=errors)
    async def delete_workspace(workspace_id: UUID) -> None:
        current_store().delete_workspace(workspace_id)

    @app.put(prefix + "/editor", response_model=Preview, responses=errors)
    async def save_editor(workspace_id: UUID, request: EditorRequest) -> Preview:
        return current_store().save_editor(workspace_id, request)

    @app.post(prefix + "/preview", response_model=Preview, responses=errors)
    async def preview(workspace_id: UUID) -> Preview:
        return current_store().preview(workspace_id)

    @app.delete(prefix + "/task-sets/{task_set_id}", status_code=204, responses=errors)
    async def delete_task_set(
        workspace_id: UUID, task_set_id: UUID, expected_revision: int
    ) -> None:
        current_store().delete_task_set(workspace_id, task_set_id, expected_revision)

    @app.post(prefix + "/runs", response_model=RunStatus, status_code=202, responses=errors)
    async def start_run(workspace_id: UUID, request: RunRequest) -> RunStatus:
        return await current_coordinator().start_run(workspace_id, request)

    @app.get(prefix + "/runs/{run_id}", response_model=RunStatus, responses=errors)
    async def run(workspace_id: UUID, run_id: UUID) -> RunStatus:
        return current_store().run(workspace_id, run_id).status

    @app.get(
        prefix + "/runs/{run_id}/outcomes",
        response_model=list[OutcomeSummary],
        responses=errors,
    )
    async def outcomes(
        workspace_id: UUID, run_id: UUID, after: int = Query(0, ge=0)
    ) -> list[OutcomeSummary]:
        return sorted(
            [
                o
                for o in current_store().run(workspace_id, run_id).status.outcomes
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
    async def cancel(workspace_id: UUID, run_id: UUID) -> RunStatus:
        return await current_coordinator().cancel_run(workspace_id, run_id)

    @app.post(prefix + "/runs/{run_id}/resume", response_model=RunStatus, responses=errors)
    async def resume(workspace_id: UUID, run_id: UUID) -> RunStatus:
        return current_coordinator().resume(workspace_id, run_id)

    @app.post(prefix + "/runs/{run_id}/comparison", response_model=Workspace, responses=errors)
    async def comparison(
        workspace_id: UUID, run_id: UUID, mutation: ComparisonMutation
    ) -> Workspace:
        return current_store().comparison(workspace_id, run_id, mutation.action)

    @app.get(
        prefix + "/runs/{run_id}/results/{scenario_id}",
        response_model=ResultView,
        responses=errors,
    )
    async def result(workspace_id: UUID, run_id: UUID, scenario_id: UUID) -> ResultView:
        record = current_store().run(workspace_id, run_id)
        result = current_store().result(record, scenario_id)
        scenario = next(o.scenario for o in record.status.outcomes if o.scenario.id == scenario_id)
        metrics = plot_data(result, sum(t.initial_value for t in record.task_set.tasks))
        insights = [
            o
            for o in observations(metrics, scenario.settings)
            if o.property not in {"qa_size", "team_size", "toolchain_size"}
            or ((o.value is not None) and (int(o.value) <= settings.max_resources))
        ]
        return ResultView(scenario_id=scenario_id, metrics=metrics, observations=insights)

    @app.get(
        prefix + "/runs/{run_id}/exports/{kind}",
        responses={200: {"content": {"text/csv": {}}}, **errors},
    )
    async def export(workspace_id: UUID, run_id: UUID, kind: str) -> StreamingResponse:
        if kind != "summary" and kind != "events" and kind != "resources":
            raise AppError("INVALID_INPUT", "Choose summary, events, or resources")
        record = current_store().run(workspace_id, run_id)
        if record.status.state not in TERMINAL:
            raise AppError(
                "RUN_ACTIVE",
                "Wait for completion or cancel before exporting a stable comparison",
                409,
            )
        # Snapshot both rows and result references before streaming across threads.

        snapshot = copy.copy(record)
        snapshot.status = record.status.model_copy(deep=True)
        frozen_results = {sid: current_store().result(record, sid) for sid in record.results}

        class ExportStore:
            """Stores generated exports for later download."""

            def result(self, record: RunRecord, scenario_id: UUID) -> ResultData:
                return frozen_results[scenario_id]

        return StreamingResponse(
            export_csv(ExportStore(), snapshot, kind),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{kind}-{run_id}.csv"'},
        )

    class CachedAssets(StaticFiles):
        """Serves cached frontend assets."""

        async def get_response(self, path: str, scope: Scope) -> Response:
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    static = Path(__file__).parent / "static"
    if (static / "assets").exists():
        app.mount("/assets", CachedAssets(directory=static / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> Response:
        if not (static / "index.html").is_file():
            return JSONResponse(
                {
                    "code": "ASSETS_MISSING",
                    "message": "Build the UI: npm run build --prefix src/value_stream/app/frontend",
                },
                status_code=503,
            )
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app

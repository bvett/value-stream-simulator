"""HTTP application for version 1 simulation jobs."""

from contextlib import asynccontextmanager
import logging
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .job_store import CapacityExceeded, InMemoryJobStore, JobNotFound, JobStorage
from .scheduler import ModelScheduler
from .schemas import (
    ErrorEnvelope,
    HealthResponse,
    JobAccepted,
    JobRequest,
    JobStatus,
    OutcomePage,
)
from .settings import ServiceSettings


logger = logging.getLogger(__name__)


def _error(
    status: int, code: str, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    body = ErrorEnvelope(code=code, message=message, details=details)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


class BodyLimitMiddleware:
    """Buffer at most the configured request size before passing it downstream."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (
            scope["method"] != "POST" or scope["path"] != "/v1/simulation-jobs"
        ):
            await self.app(scope, receive, send)
            return

        length = Headers(scope=scope).get("content-length")
        if length is not None:
            try:
                declared_size = int(length)
            except ValueError:
                await _error(422, "INVALID_INPUT", "invalid content-length header")(
                    scope, receive, send
                )
                return
            if declared_size > self.max_body_bytes:
                await _error(413, "BODY_TOO_LARGE", "request body exceeds configured limit")(
                    scope, receive, send
                )
                return

        buffered: list[Message] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_body_bytes:
                await _error(413, "BODY_TOO_LARGE", "request body exceeds configured limit")(
                    scope, receive, send
                )
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        cursor = 0

        async def replay_receive() -> Message:
            nonlocal cursor
            if cursor < len(buffered):
                message = buffered[cursor]
                cursor += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


def create_app(
    settings: ServiceSettings | None = None,
    store: JobStorage | None = None,
) -> FastAPI:
    settings = settings or ServiceSettings.from_environment()
    store = store or InMemoryJobStore(settings)
    scheduler = ModelScheduler(store, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        scheduler.close()

    application = FastAPI(
        title="Value Stream Simulation Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        BodyLimitMiddleware, max_body_bytes=settings.max_body_bytes
    )
    application.state.store = store
    application.state.scheduler = scheduler
    application.state.settings = settings

    @application.exception_handler(RequestValidationError)
    async def invalid_input(_request: Request, exc: RequestValidationError):
        issues = [
            {"location": list(item["loc"]), "message": item["msg"]}
            for item in exc.errors()
        ]
        return _error(422, "INVALID_INPUT", "request validation failed", {"issues": issues})

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        logger.exception("unexpected service error", exc_info=exc)
        return _error(500, "INTERNAL_ERROR", "unexpected service error")

    errors: dict[int | str, dict[str, Any]] = {
        404: {"model": ErrorEnvelope},
        413: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    }

    @application.get("/health", response_model=HealthResponse)
    def health():
        return HealthResponse()

    @application.post(
        "/v1/simulation-jobs",
        response_model=JobAccepted,
        status_code=202,
        responses=errors,
    )
    def submit(request: JobRequest):
        if len(request.tasks) > settings.max_tasks or len(request.models) > settings.max_models:
            return _error(422, "LIMIT_EXCEEDED", "task or model count exceeds configured limit")
        try:
            job_id = store.create(len(request.models))
        except CapacityExceeded:
            return _error(429, "JOB_CAPACITY", "job capacity is full")
        try:
            scheduler.submit(job_id, request)
        except Exception:
            store.cancel(job_id)
            raise
        return JobAccepted(
            job_id=job_id,
            status="queued",
            status_url=f"/v1/simulation-jobs/{job_id}",
        )

    @application.get(
        "/v1/simulation-jobs/{job_id}", response_model=JobStatus, responses=errors
    )
    def status(job_id: UUID):
        try:
            return store.status(job_id)
        except JobNotFound:
            return _error(404, "JOB_NOT_FOUND", "job is unknown or expired")

    @application.get(
        "/v1/simulation-jobs/{job_id}/outcomes",
        response_model=OutcomePage,
        responses=errors,
    )
    def outcomes(job_id: UUID, after: int = Query(default=0, ge=0)):
        try:
            return store.page(job_id, after)
        except JobNotFound:
            return _error(404, "JOB_NOT_FOUND", "job is unknown or expired")

    @application.delete(
        "/v1/simulation-jobs/{job_id}",
        response_model=JobStatus,
        status_code=202,
        responses=errors,
    )
    def cancel(job_id: UUID):
        try:
            scheduler.cancel(job_id)
            return store.status(job_id)
        except JobNotFound:
            return _error(404, "JOB_NOT_FOUND", "job is unknown or expired")

    return application


app = create_app()

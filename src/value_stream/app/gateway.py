"""HTTP-only simulation boundary with bounded reads and owned startup."""

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID
import httpx
from value_stream.client.web.local_service import acquire_local_service, release_local_service
from value_stream.service.schemas import JobRequest, JobAccepted, JobStatus, OutcomePage
from .errors import AppError
from .storage import UpstreamKind
from value_stream.service.persistence.config import DatabaseConfig


class SimulationGateway(Protocol):
    """Defines the interface for submitting simulation jobs."""

    async def start(self) -> None: ...
    async def ready(self) -> None: ...
    async def submit(self, request: JobRequest) -> JobAccepted: ...
    async def status(self, job_id: UUID) -> JobStatus: ...
    async def outcomes(self, job_id: UUID, after: int) -> OutcomePage: ...
    async def cancel(self, job_id: UUID) -> JobStatus: ...
    async def close(self) -> None: ...


class HttpSimulationGateway:
    """Submits simulation jobs through the HTTP service."""

    def __init__(
        self,
        url: str | None = None,
        max_response_bytes: int = 65 * 1024 * 1024,
        *,
        database: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        """Configure the upstream without opening files, clients, or local servers.

        Args:
            url: External service URL, or None for the owned local service.
            max_response_bytes: Maximum buffered response size.
            database: Optional owned-local simulation database path.
            data_dir: Optional owned-local data directory.
        """
        if url and database is not None:
            raise ValueError("A service database cannot configure an external service")
        normalized = httpx.URL(url.strip()) if url else None
        if normalized is not None and (normalized.scheme, normalized.port) in (
            ("http", 80),
            ("https", 443),
        ):
            normalized = normalized.copy_with(port=None)
        self.configured_url = str(normalized).rstrip("/") if normalized is not None else None
        self.url = self.configured_url
        self.database, self.data_dir = database, data_dir
        self.local_config: DatabaseConfig | None = None
        self.owned = False
        self.client: httpx.AsyncClient | None = None
        self.startup_error: AppError | None = None
        self.max_response_bytes = max_response_bytes
        self.download = asyncio.Semaphore(1)

    @property
    def kind(self) -> UpstreamKind:
        """Identify ownership independently of a changing local TCP port."""
        return "external" if self.configured_url else "local"

    @property
    def identity(self) -> str:
        """Return the configured endpoint or resolved local database identity."""
        if self.configured_url:
            return self.configured_url
        if self.local_config is None:
            self.local_config = DatabaseConfig.resolve(
                "simulation", database=self.database, data_dir=self.data_dir
            )
        return str(self.local_config.path)

    async def start(self) -> None:
        """Connect once, allowing a failed local start to be retried explicitly."""
        if self.client is not None and not self.client.is_closed:
            return
        try:
            if not self.configured_url:
                _ = self.identity
                self.url = await asyncio.to_thread(acquire_local_service, self.local_config)
                self.owned = True
            self.client = httpx.AsyncClient(
                base_url=self.url or "", timeout=httpx.Timeout(10, connect=3), trust_env=False
            )
            self.startup_error = None
        except Exception as exc:
            self.startup_error = AppError("SERVICE_UNAVAILABLE", str(exc), 503)
            raise self.startup_error from exc

    async def request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self.client is None or self.client.is_closed:
            raise self.startup_error or AppError(
                "SERVICE_UNAVAILABLE", "Simulation service is not connected", 503
            )
        try:
            async with self.download:
                async with self.client.stream(method, path, json=body) as response:
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > self.max_response_bytes:
                            raise AppError(
                                "RESULT_TOO_LARGE",
                                "Service response exceeds the configured limit",
                                502,
                            )

                    try:
                        value = json.loads(data)
                    except ValueError as exc:
                        raise AppError(
                            "SERVICE_INVALID_RESPONSE",
                            "Service returned invalid JSON",
                            502,
                        ) from exc
                    if not isinstance(value, dict):
                        raise AppError(
                            "SERVICE_INVALID_RESPONSE",
                            "Service returned a non-object JSON response",
                            502,
                        )
                    if response.is_error:
                        raise AppError(
                            value.get("code", "SERVICE_ERROR"),
                            value.get("message", "Simulation service request failed"),
                            response.status_code,
                            value.get("details"),
                        )
                    return value
        except httpx.RequestError as exc:
            raise AppError(
                "SERVICE_UNAVAILABLE",
                "Cannot reach the simulation service. Retained results are still available.",
                503,
            ) from exc

    async def ready(self) -> None:
        await self.request("GET", "/health")
        schema = await self.request("GET", "/openapi.json")
        properties = (
            schema.get("components", {})
            .get("schemas", {})
            .get("JobRequest", {})
            .get("properties", {})
        )
        if not {"model_seeds", "submission_id"} <= properties.keys():
            raise AppError(
                "SERVICE_INCOMPATIBLE",
                "Update the simulation service: model seeds and submission "
                "identifiers are required.",
                503,
            )

    async def submit(self, request: JobRequest) -> JobAccepted:
        return JobAccepted.model_validate(
            await self.request("POST", "/v1/simulation-jobs", request.model_dump(mode="json"))
        )

    async def status(self, job_id: UUID) -> JobStatus:
        return JobStatus.model_validate(await self.request("GET", f"/v1/simulation-jobs/{job_id}"))

    async def outcomes(self, job_id: UUID, after: int) -> OutcomePage:
        return OutcomePage.model_validate(
            await self.request("GET", f"/v1/simulation-jobs/{job_id}/outcomes?after={after}")
        )

    async def cancel(self, job_id: UUID) -> JobStatus:
        return JobStatus.model_validate(
            await self.request("DELETE", f"/v1/simulation-jobs/{job_id}")
        )

    async def close(self) -> None:
        """Close HTTP resources and release exactly one owned-local reference."""
        try:
            if self.client is not None:
                await self.client.aclose()
        finally:
            if self.owned:
                await asyncio.to_thread(release_local_service)
                self.owned = False
                self.url = self.configured_url

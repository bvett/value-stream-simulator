"""HTTP-only simulation boundary with bounded reads and owned startup."""

import asyncio
from typing import Protocol
from uuid import UUID
import httpx
from value_stream.service.schemas import JobRequest, JobAccepted, JobStatus, OutcomePage
from .errors import AppError


class SimulationGateway(Protocol):
    async def start(self): ...
    async def ready(self): ...
    async def submit(self, request: JobRequest) -> JobAccepted: ...
    async def status(self, job_id: UUID) -> JobStatus: ...
    async def outcomes(self, job_id: UUID, after: int) -> OutcomePage: ...
    async def cancel(self, job_id: UUID) -> JobStatus: ...
    async def close(self): ...


class HttpSimulationGateway:
    def __init__(self, url=None, max_response_bytes=65 * 1024 * 1024):
        self.url = url
        self.owned = False
        self.client = None
        self.max_response_bytes = max_response_bytes
        self.download = asyncio.Semaphore(1)

    async def start(self):
        if not self.url:
            from value_stream.client.web.local_service import acquire_local_service

            self.url = await asyncio.to_thread(acquire_local_service)
            self.owned = True
        self.client = httpx.AsyncClient(
            base_url=self.url, timeout=httpx.Timeout(10, connect=3), trust_env=False
        )

    async def request(self, method, path, body=None):
        if self.client is None or self.client.is_closed:
            raise AppError("SERVICE_UNAVAILABLE", "Simulation service is not connected", 503)
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
                    import json

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

    async def ready(self):
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
                "Update the simulation service: model seeds and submission identifiers are required.",
                503,
            )

    async def submit(self, request):
        return JobAccepted.model_validate(
            await self.request("POST", "/v1/simulation-jobs", request.model_dump(mode="json"))
        )

    async def status(self, job_id):
        return JobStatus.model_validate(await self.request("GET", f"/v1/simulation-jobs/{job_id}"))

    async def outcomes(self, job_id, after):
        return OutcomePage.model_validate(
            await self.request("GET", f"/v1/simulation-jobs/{job_id}/outcomes?after={after}")
        )

    async def cancel(self, job_id):
        return JobStatus.model_validate(
            await self.request("DELETE", f"/v1/simulation-jobs/{job_id}")
        )

    async def close(self):
        if self.client:
            await self.client.aclose()
        if self.owned:
            from value_stream.client.web.local_service import release_local_service

            await asyncio.to_thread(release_local_service)
            self.owned = False

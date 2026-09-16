"""Python HTTP client for simulation jobs."""

import time
from collections.abc import Iterable

import httpx
from pydantic import ValidationError
from tqdm import tqdm

from value_stream.service.codec import decode_result, encode_request
from value_stream.service.schemas import JobAccepted, JobStatus, ModelError, OutcomePage
from value_stream.simulation import Model, SimulationResult
from value_stream.task import Task

from .errors import BatchSimulationError, JobCancelledError, ServiceClientError


class WebSimulationClient:
    def __init__(
        self, service_url: str, poll_interval: float = 0.1,
        max_wait_seconds: float = 3600,
    ):
        self.service_url = service_url.rstrip("/")
        self.poll_interval = poll_interval
        self.max_wait_seconds = max_wait_seconds
        self._http = httpx.Client(base_url=self.service_url, timeout=5, trust_env=False)

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            try:
                data = exc.response.json()
                message = f"{data.get('code', 'HTTP_ERROR')}: {data.get('message', exc)}"
            except ValueError:
                message = str(exc)
            raise ServiceClientError(message) from exc
        except httpx.RequestError as exc:
            raise ServiceClientError(f"service connection failed: {exc}") from exc

    @staticmethod
    def _validate(model_type, value: dict, description: str):
        try:
            return model_type.model_validate(value)
        except ValidationError as exc:
            raise ServiceClientError(f"service returned malformed {description}") from exc

    def execute(
        self,
        tasks: list[Task],
        models: Iterable[Model],
        pbar: tqdm | None = None,
        seed: int | None = None,
    ) -> list[SimulationResult]:
        model_list = list(models)
        request = encode_request(tasks, model_list, seed)
        submitted = self._validate(JobAccepted,
            self._request(
                "POST", "/v1/simulation-jobs", json=request.model_dump(mode="json")
            ).json(), "job acceptance"
        )
        job_path = f"/v1/simulation-jobs/{submitted.job_id}"
        results: dict[int, SimulationResult] = {}
        errors: dict[int, ModelError] = {}
        cursor = 0
        deadline = time.monotonic() + self.max_wait_seconds
        while True:
            if time.monotonic() >= deadline:
                raise ServiceClientError(f"job {submitted.job_id} exceeded client wait limit")
            page = self._validate(
                OutcomePage,
                self._request("GET", f"{job_path}/outcomes", params={"after": cursor}).json(),
                "outcomes",
            )
            for outcome in page.outcomes:
                if not 0 <= outcome.model_index < len(model_list):
                    raise ServiceClientError("service returned an invalid model index")
                if outcome.status == "succeeded" and outcome.result is not None:
                    results[outcome.model_index] = decode_result(
                        outcome.result, model_list[outcome.model_index]
                    )
                elif outcome.status == "failed" and outcome.error is not None:
                    errors[outcome.model_index] = outcome.error
                if pbar:
                    pbar.update()
            cursor = page.next_cursor
            status = self._validate(
                JobStatus, self._request("GET", job_path).json(), "job status"
            )
            if status.total_models != len(model_list):
                raise ServiceClientError("service returned an unexpected model count")
            if status.status in ("completed", "completed_with_errors", "cancelled"):
                if cursor < status.total_models:
                    continue
                if status.status == "cancelled":
                    raise JobCancelledError(f"job {submitted.job_id} was cancelled")
                break
            time.sleep(self.poll_interval)
        successful = sorted(results.items())
        if errors:
            if len(successful) + len(errors) != len(model_list):
                raise ServiceClientError("service omitted a model outcome")
            raise BatchSimulationError(successful_results=successful, errors=errors)
        if len(successful) != len(model_list):
            raise ServiceClientError("service omitted a model result")
        return [result for _, result in successful]

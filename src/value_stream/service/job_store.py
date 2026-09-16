"""Bounded in-memory job state, replaceable by a shared store later."""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from .schemas import JobState, JobStatus, ModelError, OutcomeData, OutcomePage, ResultData
from .settings import ServiceSettings


class JobNotFound(Exception):
    pass


class CapacityExceeded(Exception):
    pass


class JobStorage(Protocol):
    def create(self, model_count: int) -> UUID: ...
    def status(self, job_id: UUID) -> JobStatus: ...
    def page(self, job_id: UUID, after: int) -> OutcomePage: ...
    def start_model(self, job_id: UUID, index: int) -> bool: ...
    def finish_model(
        self, job_id: UUID, index: int, result: ResultData | None, error: ModelError | None
    ) -> None: ...
    def cancel(self, job_id: UUID) -> None: ...


@dataclass
class _Job:
    job_id: UUID
    states: list[str]
    created_at: float
    status: JobState = "queued"
    outcomes: list[OutcomeData] = field(default_factory=list[OutcomeData])
    result_bytes: int = 0
    terminal_at: float | None = None


class InMemoryJobStore:
    def __init__(self, settings: ServiceSettings):
        self.settings = settings
        self._jobs: dict[UUID, _Job] = {}
        self._lock = threading.RLock()

    def _prune(self):
        now = time.monotonic()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.terminal_at is not None
            and now - job.terminal_at >= self.settings.job_ttl_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]

    def _get(self, job_id: UUID) -> _Job:
        self._prune()
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFound(str(job_id)) from exc

    def _retained_bytes(self) -> int:
        return sum(job.result_bytes for job in self._jobs.values())

    def create(self, model_count: int) -> UUID:
        with self._lock:
            self._prune()
            nonterminal = sum(job.terminal_at is None for job in self._jobs.values())
            if (
                len(self._jobs) >= self.settings.max_retained_jobs
                or self._retained_bytes() >= self.settings.max_retained_bytes
                or nonterminal >= self.settings.max_active_jobs + self.settings.max_queued_jobs
            ):
                raise CapacityExceeded("job capacity is full")
            job_id = uuid.uuid4()
            self._jobs[job_id] = _Job(
                job_id=job_id,
                states=["queued"] * model_count,
                created_at=time.monotonic(),
            )
            return job_id

    def status(self, job_id: UUID) -> JobStatus:
        with self._lock:
            job = self._get(job_id)
            counts = {state: job.states.count(state) for state in (
                "queued", "running", "succeeded", "failed", "cancelled"
            )}
            return JobStatus(
                job_id=job_id,
                status=job.status,
                total_models=len(job.states),
                queued_models=counts["queued"],
                running_models=counts["running"],
                succeeded_models=counts["succeeded"],
                failed_models=counts["failed"],
                cancelled_models=counts["cancelled"],
                last_cursor=len(job.outcomes),
            )

    def page(self, job_id: UUID, after: int) -> OutcomePage:
        with self._lock:
            job = self._get(job_id)
            outcomes = [item for item in job.outcomes if item.cursor > after]
            return OutcomePage(outcomes=outcomes, next_cursor=len(job.outcomes))

    def start_model(self, job_id: UUID, index: int) -> bool:
        with self._lock:
            job = self._get(job_id)
            if job.states[index] != "queued":
                return False
            job.states[index] = "running"
            job.status = "running"
            return True

    def _terminal(self, job: _Job):
        if all(state in ("succeeded", "failed", "cancelled") for state in job.states):
            if job.status != "cancelled":
                job.status = (
                    "completed_with_errors" if "failed" in job.states else "completed"
                )
            job.terminal_at = time.monotonic()

    def finish_model(
        self, job_id: UUID, index: int, result: ResultData | None, error: ModelError | None
    ) -> None:
        with self._lock:
            job = self._get(job_id)
            if job.states[index] not in ("queued", "running"):
                return
            if result is not None:
                size = len(result.model_dump_json().encode("utf-8"))
                if (
                    size > self.settings.max_model_outcome_bytes
                    or job.result_bytes + size > self.settings.max_job_outcome_bytes
                    or self._retained_bytes() + size > self.settings.max_retained_bytes
                ):
                    result = None
                    error = ModelError(
                        model_index=index,
                        code="RESULT_TOO_LARGE",
                        message="model result exceeds configured storage limit",
                    )
                else:
                    job.result_bytes += size
            if result is None and error is None:
                error = ModelError(
                    model_index=index, code="WORKER_FAILED", message="model worker failed"
                )
            state = "succeeded" if result is not None else "failed"
            job.states[index] = state
            job.outcomes.append(
                OutcomeData(
                    cursor=len(job.outcomes) + 1,
                    model_index=index,
                    status=state,
                    result=result,
                    error=error,
                )
            )
            self._terminal(job)

    def cancel(self, job_id: UUID) -> None:
        with self._lock:
            job = self._get(job_id)
            if job.terminal_at is not None:
                return
            job.status = "cancelled"
            for index, state in enumerate(job.states):
                if state in ("queued", "running"):
                    job.states[index] = "cancelled"
                    job.outcomes.append(
                        OutcomeData(
                            cursor=len(job.outcomes) + 1,
                            model_index=index,
                            status="cancelled",
                        )
                    )
            job.terminal_at = time.monotonic()

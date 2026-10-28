"""Shared transactional job transitions and a bounded in-memory adapter."""

import copy
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ContextManager, Protocol
from uuid import UUID

from .schemas import JobState, JobStatus, ModelError, OutcomeData, OutcomePage, ResultData, Status
from .settings import ServiceSettings


class JobNotFound(Exception):
    """Indicates that a requested job does not exist."""


class CapacityExceeded(Exception):
    """Indicates that the job store has reached its capacity."""


class SubmissionConflict(Exception):
    """Indicates that a submission conflicts with an existing job."""


class JobStorage(Protocol):
    """Defines storage operations for simulation jobs."""

    def create(self, model_count: int) -> UUID: ...
    def reserve(
        self, model_count: int, submission_id: UUID | None, fingerprint: str
    ) -> tuple[UUID, bool]: ...
    def status(self, job_id: UUID) -> JobStatus: ...
    def page(self, job_id: UUID, after: int) -> OutcomePage: ...
    def start_model(self, job_id: UUID, index: int) -> bool: ...
    def finish_model(
        self,
        job_id: UUID,
        index: int,
        result: ResultData | None,
        error: ModelError | None,
    ) -> None: ...
    def cancel(self, job_id: UUID) -> None: ...
    def interrupt_unfinished(self) -> None:
        """Commit interruption outcomes for every unfinished model."""
        ...

    def close(self) -> None:
        """Release resources after scheduling and workers have stopped."""
        ...


@dataclass
class _Job:
    """Detached job state with committed completion order and UTC timestamps."""

    job_id: UUID
    states: list[str]
    created_at: float
    status: JobState = "queued"
    outcomes: list[OutcomeData] = field(default_factory=list[OutcomeData])
    result_bytes: int = 0
    terminal_at: float | None = None
    last_cursor: int = 0


class JobOperations(ABC):
    """Shared terminal transitions over transactional detached job snapshots."""

    @abstractmethod
    def _atomic(self) -> ContextManager[object]:
        """Open one serialized operation and roll back failed persistent writes."""

    @abstractmethod
    def _get(self, job_id: UUID) -> _Job:
        """Return a detached job or raise JobNotFound."""

    @abstractmethod
    def _save(self, job: _Job) -> None:
        """Publish a validated transition inside the current operation."""

    @abstractmethod
    def _unfinished(self) -> list[UUID]:
        """List unfinished jobs before expiry."""

    @abstractmethod
    def _retained_bytes(self) -> int:
        """Return logical retained result usage."""

    @abstractmethod
    def create(self, model_count: int) -> UUID:
        """Reserve a job without a submission identity."""

    @abstractmethod
    def reserve(
        self, model_count: int, submission_id: UUID | None, fingerprint: str
    ) -> tuple[UUID, bool]:
        """Atomically resolve an idempotent retry or reserve new work."""

    @abstractmethod
    def close(self) -> None:
        """Release owned backend resources after worker shutdown."""

    settings: ServiceSettings

    def interrupt_unfinished(self) -> None:
        """Finalize unfinished models atomically, preserving earlier completions."""
        with self._atomic():
            for job_id in self._unfinished():
                job = self._get(job_id)
                for index, state in enumerate(job.states):
                    if state in ("queued", "running"):
                        job.states[index] = "failed"
                        job.outcomes.append(
                            OutcomeData(
                                cursor=job.last_cursor + 1,
                                model_index=index,
                                status=Status.FAILED,
                                error=ModelError(
                                    model_index=index,
                                    code="JOB_INTERRUPTED",
                                    message="simulation service stopped before model completion",
                                ),
                            )
                        )
                        job.last_cursor += 1
                self._terminal(job)
                self._save(job)

    def status(self, job_id: UUID) -> JobStatus:
        """Return the current job status.

        Args:
            job_id (UUID): Identifier of the job.

        Returns:
            JobStatus: Current status of the requested job.
        """
        with self._atomic():
            job = self._get(job_id)
            counts = {
                state: job.states.count(state)
                for state in ("queued", "running", "succeeded", "failed", "cancelled")
            }
            return JobStatus(
                job_id=job_id,
                status=job.status,
                total_models=len(job.states),
                queued_models=counts["queued"],
                running_models=counts["running"],
                succeeded_models=counts["succeeded"],
                failed_models=counts["failed"],
                cancelled_models=counts["cancelled"],
                last_cursor=job.last_cursor,
            )

    def page(self, job_id: UUID, after: int) -> OutcomePage:
        """Return a page of job outcomes.

        Args:
            job_id (UUID): Identifier of the job.
            after (int): Outcome cursor after which to return records.

        Returns:
            OutcomePage: A page of outcomes after the supplied cursor.
        """
        with self._atomic():
            job = self._get(job_id)
            outcomes = [item for item in job.outcomes if item.cursor > after]
            return OutcomePage(outcomes=outcomes, next_cursor=job.last_cursor)

    def start_model(self, job_id: UUID, index: int) -> bool:
        """Mark a model as started.

        Args:
            job_id (UUID): Identifier of the job.
            index (int): Index of the scenario or model.

        Returns:
            bool: Whether the model was newly marked as started.
        """
        with self._atomic():
            job = self._get(job_id)
            if not 0 <= index < len(job.states):
                raise IndexError(index)
            if job.states[index] != "queued":
                return False
            job.states[index] = "running"
            job.status = "running"
            self._save(job)
            return True

    def _terminal(self, job: _Job) -> None:
        """Check whether a job has reached a terminal state.

        Args:
            job (_Job): Job.
        """
        if all(state in ("succeeded", "failed", "cancelled") for state in job.states):
            if job.status != "cancelled":
                job.status = "completed_with_errors" if "failed" in job.states else "completed"
            job.terminal_at = time.time()

    def finish_model(
        self,
        job_id: UUID,
        index: int,
        result: ResultData | None,
        error: ModelError | None,
    ) -> None:
        """Record the completion of a model.

        Args:
            job_id (UUID): Identifier of the job.
            index (int): Index of the scenario or model.
            result (ResultData | None): Simulation result to retain.
            error (ModelError | None): Error information to record.
        """
        with self._atomic():
            job = self._get(job_id)
            if not 0 <= index < len(job.states):
                raise IndexError(index)
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
                    model_index=index,
                    code="WORKER_FAILED",
                    message="model worker failed",
                )
            if result is not None:
                error = None
            state = Status.SUCCEEDED if result is not None else Status.FAILED
            job.states[index] = state
            job.outcomes.append(
                OutcomeData(
                    cursor=job.last_cursor + 1,
                    model_index=index,
                    status=state,
                    result=result,
                    error=error,
                )
            )
            job.last_cursor += 1
            self._terminal(job)
            self._save(job)

    def cancel(self, job_id: UUID) -> None:
        """Cancel the requested job.

        Args:
            job_id (UUID): Identifier of the job.
        """
        with self._atomic():
            job = self._get(job_id)
            if job.terminal_at is not None:
                return
            job.status = "cancelled"
            for index, state in enumerate(job.states):
                if state in ("queued", "running"):
                    job.states[index] = "cancelled"
                    job.outcomes.append(
                        OutcomeData(
                            cursor=job.last_cursor + 1,
                            model_index=index,
                            status=Status.CANCELLED,
                        )
                    )
                    job.last_cursor += 1
            job.terminal_at = time.time()
            self._save(job)


class InMemoryJobStore(JobOperations):
    """Store detached simulation job snapshots in memory."""

    def __init__(self, settings: ServiceSettings) -> None:
        """Initialize job retention and capacity limits.

        Args:
            settings (ServiceSettings): Settings to validate or use.
        """
        self.settings = settings
        self._jobs: dict[UUID, _Job] = {}
        self._lock = threading.RLock()
        self._submissions: dict[UUID, tuple[str, UUID]] = {}

    def _atomic(self) -> ContextManager[object]:
        """Serialize one complete storage operation."""
        return self._lock

    def _save(self, job: _Job) -> None:
        """Publish a fully validated job snapshot."""
        self._jobs[job.job_id] = copy.deepcopy(job)

    def _unfinished(self) -> list[UUID]:
        """Return unfinished identifiers without applying terminal expiry."""
        return [key for key, job in self._jobs.items() if job.terminal_at is None]

    def close(self) -> None:
        """Release storage resources; memory storage owns no external resources."""

    def _prune(self) -> None:
        """Remove expired terminal jobs and their submission mappings."""
        now = time.time()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.terminal_at is not None
            and now - job.terminal_at >= self.settings.job_ttl_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]
        self._submissions = {
            key: value for key, value in self._submissions.items() if value[1] in self._jobs
        }

    def _get(self, job_id: UUID) -> _Job:
        """Return the job with the requested identifier.

        Args:
            job_id (UUID): Identifier of the job.

        Raises:
            JobNotFound: If the requested job does not exist.

        Returns:
            _Job: Stored job for the identifier.
        """
        self._prune()
        try:
            return copy.deepcopy(self._jobs[job_id])
        except KeyError as exc:
            raise JobNotFound(str(job_id)) from exc

    def _retained_bytes(self) -> int:
        """Return the number of bytes retained by the job store.

        Returns:
            int: Total bytes currently retained for job results.
        """
        return sum(job.result_bytes for job in self._jobs.values())

    def create(self, model_count: int) -> UUID:
        """Create and store a simulation job.

        Args:
            model_count (int): Model count.

        Raises:
            CapacityExceeded: If configured retained or active capacity is full.
            ValueError: If the requested model count is not positive.

        Returns:
            UUID: Identifier assigned to the new job.
        """
        with self._atomic():
            self._prune()
            nonterminal = sum(job.terminal_at is None for job in self._jobs.values())
            if (
                len(self._jobs) >= self.settings.max_retained_jobs
                or self._retained_bytes() >= self.settings.max_retained_bytes
                or nonterminal >= self.settings.max_active_jobs + self.settings.max_queued_jobs
            ):
                raise CapacityExceeded("job capacity is full")
            if model_count <= 0:
                raise ValueError("A job requires at least one model")
            job_id = uuid.uuid4()
            self._jobs[job_id] = _Job(
                job_id=job_id,
                states=["queued"] * model_count,
                created_at=time.time(),
            )
            return job_id

    def reserve(
        self, model_count: int, submission_id: UUID | None, fingerprint: str
    ) -> tuple[UUID, bool]:
        """Reserve capacity for a job.

        Args:
            model_count (int): Model count.
            submission_id (UUID | None): Client supplied identifier for deduplicating submissions.
            fingerprint (str): Fingerprint of the submitted job payload.

        Raises:
            SubmissionConflict: If the submission identifier has different inputs.
            CapacityExceeded: If capacity cannot be reserved for new work.

        Returns:
            tuple[UUID, bool]: The existing or newly reserved job identifier
                and whether it was created.
        """
        with self._atomic():
            self._prune()
            if submission_id is not None and submission_id in self._submissions:
                previous, job_id = self._submissions[submission_id]
                if previous != fingerprint:
                    raise SubmissionConflict("submission ID already used for different inputs")
                return job_id, False
            job_id = self.create(model_count)
            if submission_id is not None:
                self._submissions[submission_id] = (fingerprint, job_id)
            return job_id, True

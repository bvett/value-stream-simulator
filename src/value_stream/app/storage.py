"""Transactional workspace rules with detached snapshots and replaceable storage."""

import copy
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import ContextManager, Iterator, Literal, Protocol
from uuid import UUID, uuid4

from value_stream.service.schemas import ErrorEnvelope, ResultData, Status
from .errors import AppError
from .generation import canonical, expand_scenarios, fingerprint, materialize_tasks
from .metrics import loss_percent
from .schemas import (
    ENGINE_VERSION,
    GENERATOR_VERSION,
    TERMINAL,
    ConcreteScenario,
    EditorRequest,
    OutcomeSummary,
    Preview,
    RunRequest,
    RunState,
    RunStatus,
    TaskSet,
    Workspace,
)
from .settings import AppSettings

UpstreamKind = Literal["local", "external"]


class Unchanged(Enum):
    """Distinguish an omitted patch value from explicitly clearing an error."""

    VALUE = "unchanged"


@dataclass(frozen=True)
class RunChanges:
    """Explicit run fields to update, preserving unrelated concurrent changes."""

    state: RunState | None = None
    job_id: UUID | None = None
    upstream_kind: UpstreamKind | None = None
    upstream_identity: str | None = None
    cancel_requested: bool | None = None
    superseded: bool | None = None
    retry_paused: bool | None = None
    error: ErrorEnvelope | None | Unchanged = Unchanged.VALUE


@dataclass(frozen=True)
class CompletedOutcome:
    """One final scenario outcome and its optional upstream completion cursor.

    Attributes:
        index: Scenario position within the frozen application run.
        status: Final scenario state; pending states are rejected at commit.
        result: Successful result, mutually exclusive with an error.
        error: Failure details, required for a failed scenario.
        cached: Whether the result was reused rather than executed upstream.
        service_cursor: Upstream completion position, required for service pages.
    """

    index: int
    status: Status
    result: ResultData | None = None
    error: ErrorEnvelope | None = None
    cached: bool = False
    service_cursor: int | None = None


@dataclass
class RunRecord:
    """A detached run snapshot, with references to independently retained results."""

    workspace_id: UUID
    status: RunStatus
    task_set: TaskSet
    request: RunRequest
    request_hash: str
    cache_keys: list[str]
    results: dict[UUID, str] = field(default_factory=dict)
    service_indices: list[int] = field(default_factory=list)
    service_cursor: int = 0
    service_outcomes: dict[int, int] = field(default_factory=dict)
    reservation: int = 0
    result_bytes: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    upstream_kind: UpstreamKind | None = None
    upstream_identity: str | None = None


@dataclass(frozen=True)
class StorageUsage:
    """Durable byte/count usage, independent of any result read cache."""

    workspaces: int
    input_bytes: int
    result_bytes: int
    reservations: int
    active_runs: int


class WorkspaceStore(Protocol):
    """Application operations; returned values never mutate storage implicitly."""

    settings: AppSettings

    def create(self) -> Workspace:
        """Create a saved workspace within configured admission limits."""
        ...

    def get(self, workspace_id: UUID) -> Workspace:
        """Read a detached workspace and its run summaries."""
        ...

    def run(self, workspace_id: UUID, run_id: UUID) -> RunRecord:
        """Read a detached run owned by the requested workspace."""
        ...

    def save_editor(self, workspace_id: UUID, request: EditorRequest) -> Preview:
        """Atomically validate and save editor changes using its revision."""
        ...

    def preview(self, workspace_id: UUID) -> Preview:
        """Expand the currently saved editor into frozen scenarios."""
        ...

    def register(
        self,
        workspace_id: UUID,
        request: RunRequest,
        scenarios: list[ConcreteScenario],
        task_set: TaskSet,
    ) -> tuple[RunRecord, bool]:
        """Deduplicate or atomically admit a run and reserve result capacity."""
        ...

    def previous(self, workspace: Workspace, request: RunRequest) -> RunRecord | None:
        """Find a saved matching request before admission checks."""
        ...

    def patch_run(self, workspace_id: UUID, run_id: UUID, changes: RunChanges) -> RunRecord:
        """Commit explicit run changes without replacing unrelated fields."""
        ...

    def complete_outcomes(
        self,
        workspace_id: UUID,
        run_id: UUID,
        outcomes: list[CompletedOutcome],
        *,
        service_cursor: int | None = None,
        terminal_state: RunState | None = None,
        run_error: ErrorEnvelope | None = None,
    ) -> RunRecord:
        """Commit a complete outcome page and its checkpoint together."""
        ...

    def cached_result(self, key: str) -> ResultData:
        """Read an independent reusable result payload."""
        ...

    def result(self, record: RunRecord, scenario_id: UUID) -> ResultData:
        """Read a retained result using its frozen run snapshot."""
        ...

    def active_records(self) -> list[tuple[UUID, RunRecord]]:
        """List active owner/run snapshots for lifecycle coordination."""
        ...

    def comparison(self, workspace_id: UUID, run_id: UUID, action: str) -> Workspace:
        """Apply an explicit pin, unpin, baseline, or delete action."""
        ...

    def delete_workspace(self, workspace_id: UUID) -> None:
        """Explicitly remove an inactive workspace and its saved data."""
        ...

    def delete_task_set(
        self, workspace_id: UUID, task_set_id: UUID, expected_revision: int
    ) -> None:
        """Delete an unused task set with an optimistic revision guard."""
        ...

    def close(self) -> None:
        """Release adapter-owned resources after operations finish."""
        ...


class WorkspaceOperations(ABC):
    """Storage-independent mutation rules implemented using atomic backend primitives."""

    settings: AppSettings

    @abstractmethod
    def close(self) -> None:
        """Release adapter resources after all operations finish."""

    @abstractmethod
    def _atomic(self, write: bool = True) -> ContextManager[None]:
        """Lock a read or provide rollback for a complete write operation."""

    @abstractmethod
    def _workspace(self, workspace_id: UUID) -> Workspace | None:
        """Read a workspace and its summaries, without raw results."""

    @abstractmethod
    def _write_workspace(self, workspace: Workspace) -> None:
        """Persist editor state and task sets, excluding run mutations."""

    @abstractmethod
    def _record(self, run_id: UUID) -> RunRecord | None:
        """Read a run snapshot without raw result payloads."""

    @abstractmethod
    def _write_record(self, record: RunRecord) -> None:
        """Persist run metadata, outcomes, and result references."""

    @abstractmethod
    def _records(self) -> list[tuple[UUID, UUID]]:
        """List active workspace/run identities."""

    @abstractmethod
    def _find_request(self, workspace_id: UUID, request_id: UUID) -> RunRecord | None:
        """Look up an idempotent request before admission checks."""

    @abstractmethod
    def _blob_size(self, key: str) -> int | None:
        """Inspect result existence and size without decoding the payload."""

    @abstractmethod
    def _blob(self, key: str) -> ResultData:
        """Read a detached result payload."""

    @abstractmethod
    def _put_blob(self, key: str, result: ResultData, size: int) -> None:
        """Insert a new immutable result."""

    @abstractmethod
    def _usage(self) -> StorageUsage:
        """Read durable counters and byte usage."""

    @abstractmethod
    def _remove_run(self, run_id: UUID) -> None:
        """Remove a run and its references."""

    @abstractmethod
    def _remove_workspace(self, workspace_id: UUID) -> None:
        """Remove workspace-owned inputs and runs."""

    @abstractmethod
    def _collect_blobs(self) -> None:
        """Reclaim only results with no saved or active-run references."""

    def get(self, workspace_id: UUID) -> Workspace:
        """Return an independent workspace snapshot or a structured missing error."""
        with self._atomic(False):
            workspace = self._workspace(workspace_id)
            if workspace is None:
                raise AppError("WORKSPACE_NOT_FOUND", "Workspace not found", 404)
            return workspace

    def run(self, workspace_id: UUID, run_id: UUID) -> RunRecord:
        """Read a run only when it belongs to the requested workspace."""
        with self._atomic(False):
            self.get(workspace_id)
            record = self._record(run_id)
            if record is None or record.workspace_id != workspace_id:
                raise AppError("RUN_NOT_FOUND", "Run not found", 404)
            return record

    def _check_inputs(self, previous: int) -> None:
        """Reject increased input usage over the limit without removing saved work."""
        current = self._usage().input_bytes
        if current > self.settings.max_input_bytes and current > previous:
            raise AppError("APP_CAPACITY", "Input storage limit reached. Delete saved data.", 429)

    def create(self) -> Workspace:
        """Create a workspace atomically within configured input/count limits."""
        with self._atomic():
            usage = self._usage()
            if usage.workspaces >= self.settings.max_workspaces:
                raise AppError(
                    "APP_CAPACITY", "Workspace limit reached. Delete an unused workspace.", 429
                )
            workspace = Workspace()
            self._write_workspace(workspace)
            self._check_inputs(usage.input_bytes)
            return self.get(workspace.id)

    def save_editor(self, workspace_id: UUID, request: EditorRequest) -> Preview:
        """Validate and atomically save editor inputs using an optimistic revision."""
        with self._atomic():
            workspace = self.get(workspace_id)
            previous = self._usage().input_bytes
            if request.expected_revision != workspace.revision:
                raise AppError(
                    "REVISION_CONFLICT", "Inputs changed in another tab. Reload the workspace.", 409
                )
            if request.task_spec.count > self.settings.max_tasks:
                raise AppError("LIMIT_EXCEEDED", f"Task count exceeds {self.settings.max_tasks}")
            if len({d.id for d in request.definitions}) != len(request.definitions):
                raise AppError("INVALID_INPUT", "Definition IDs must be unique")
            scenarios = expand_scenarios(request.definitions, self.settings)
            hashed = fingerprint(request.task_spec.model_dump())
            task_set = next(
                (t for t in workspace.task_sets if fingerprint(t.spec.model_dump()) == hashed), None
            )
            if task_set is None:
                if len(workspace.task_sets) >= self.settings.max_task_sets:
                    raise AppError(
                        "APP_CAPACITY", "Task-set limit reached. Remove unused task sets.", 429
                    )
                tasks = materialize_tasks(request.task_spec)
                task_set = TaskSet(
                    spec=request.task_spec.model_copy(deep=True),
                    tasks=tasks,
                    content_hash=fingerprint([t.model_dump() for t in tasks]),
                )
                workspace.task_sets.append(task_set)
            workspace.task_spec = request.task_spec.model_copy(deep=True)
            workspace.definitions = [d.model_copy(deep=True) for d in request.definitions]
            if workspace.current_task_set != task_set.id:
                workspace.baseline_id = workspace.latest_id = None
            workspace.current_task_set = task_set.id
            workspace.revision += 1
            self._write_workspace(workspace)
            self._check_inputs(previous)
            return self._preview(workspace, scenarios)

    @staticmethod
    def _preview(workspace: Workspace, scenarios: list[ConcreteScenario]) -> Preview:
        """Build the stale-input guard from frozen task identity, revision, and scenarios."""
        if workspace.current_task_set is None:
            raise AppError("INVALID_INPUT", "Save and preview inputs first")
        return Preview(
            digest=fingerprint(
                [
                    str(workspace.current_task_set),
                    workspace.revision,
                    [s.model_dump(mode="json") for s in scenarios],
                ]
            ),
            task_set_id=workspace.current_task_set,
            workspace_revision=workspace.revision,
            scenarios=scenarios,
            count=len(scenarios),
        )

    def preview(self, workspace_id: UUID) -> Preview:
        """Preview the current saved editor without mutating stored inputs."""
        workspace = self.get(workspace_id)
        return self._preview(workspace, expand_scenarios(workspace.definitions, self.settings))

    def previous(self, workspace: Workspace, request: RunRequest) -> RunRecord | None:
        """Return a matching durable request or reject reuse with different inputs."""
        with self._atomic(False):
            record = self._find_request(workspace.id, request.request_id)
            if record is not None and record.request_hash != fingerprint(
                request.model_dump(mode="json")
            ):
                raise AppError(
                    "SUBMISSION_CONFLICT", "Request ID was used with different inputs", 409
                )
            return record

    def register(
        self,
        workspace_id: UUID,
        request: RunRequest,
        scenarios: list[ConcreteScenario],
        task_set: TaskSet,
    ) -> tuple[RunRecord, bool]:
        """Reserve space and register frozen inputs without pruning saved runs.

        Args:
            workspace_id: Workspace owning the comparison.
            request: Idempotent request and preview guard.
            scenarios: Frozen scenarios expanded from the validated inputs.
            task_set: Saved task set shared by all scenarios in the run.

        Returns:
            A detached run and whether this call created it.

        Raises:
            AppError: If inputs changed, admission is full, or the request conflicts.
        """
        with self._atomic():
            workspace = self.get(workspace_id)
            previous = self.previous(workspace, request)
            if previous is not None:
                return previous, False
            if task_set.id != workspace.current_task_set:
                raise AppError("REVISION_CONFLICT", "Task set is not the current saved input", 409)
            if request.intent == "manual":
                preview = self._preview(
                    workspace, expand_scenarios(workspace.definitions, self.settings)
                )
                if request.preview_digest != preview.digest or scenarios != preview.scenarios:
                    raise AppError(
                        "REVISION_CONFLICT",
                        "Preview is stale. Preview the current inputs again.",
                        409,
                    )
            usage = self._usage()
            if any(r.state not in TERMINAL for r in workspace.runs):
                raise AppError("RUN_ACTIVE", "Cancel or finish the current run first", 409)
            if usage.active_runs >= self.settings.max_active_runs:
                raise AppError("APP_CAPACITY", "All application execution slots are occupied", 429)
            if len(workspace.runs) >= self.settings.max_retained_runs:
                raise AppError(
                    "APP_CAPACITY", "Run history is full. Delete a saved comparison.", 429
                )
            if not scenarios or len({s.id for s in scenarios}) != len(scenarios):
                raise AppError("INVALID_INPUT", "A run requires distinct scenarios")
            stored_tasks = next((t for t in workspace.task_sets if t.id == task_set.id), None)
            if stored_tasks is None or stored_tasks != task_set:
                raise AppError("REVISION_CONFLICT", "Task set does not match the saved inputs", 409)
            if request.intent == "interactive" and workspace.runs:
                latest = self.run(workspace_id, workspace.runs[-1].id)
                if max(0, time.time() - latest.created_at) < self.settings.min_interactive_seconds:
                    raise AppError(
                        "APP_CAPACITY", "Wait a moment before the next interactive comparison", 429
                    )
            keys = [
                fingerprint(
                    [
                        ENGINE_VERSION,
                        GENERATOR_VERSION,
                        task_set.content_hash,
                        s.model.model_dump(mode="json"),
                        s.execution_seed,
                    ]
                )
                for s in scenarios
            ]
            missing = [i for i, key in enumerate(keys) if self._blob_size(key) is None]
            reservation = min(
                self.settings.max_run_bytes, self.settings.max_model_bytes * len(missing)
            )
            if (
                reservation
                and usage.result_bytes + usage.reservations + reservation
                > self.settings.max_result_bytes
            ):
                raise AppError(
                    "APP_CAPACITY",
                    "Result storage is full. Delete saved comparisons or increase the limit.",
                    429,
                )
            status = RunStatus(
                id=uuid4(),
                name=request.name,
                task_set_id=task_set.id,
                state="submitting",
                intent=request.intent,
                outcomes=[OutcomeSummary(scenario=s.model_copy(deep=True)) for s in scenarios],
            )
            record = RunRecord(
                workspace_id=workspace_id,
                status=status,
                task_set=task_set,
                request=request.model_copy(deep=True),
                request_hash=fingerprint(request.model_dump(mode="json")),
                cache_keys=keys,
                service_indices=missing,
                reservation=reservation,
            )
            self._write_record(record)
            if request.intent == "interactive":
                workspace.latest_id = status.id
                self._write_workspace(workspace)
            self._check_inputs(usage.input_bytes)
            return self.run(workspace_id, status.id), True

    def patch_run(self, workspace_id: UUID, run_id: UUID, changes: RunChanges) -> RunRecord:
        """Commit explicit status/provenance changes against the latest stored state."""
        with self._atomic():
            record = self.run(workspace_id, run_id)
            if record.status.state in TERMINAL:
                return record
            if changes.state in TERMINAL:
                raise AppError("INVALID_INPUT", "Finalize runs through complete_outcomes")
            for name in ("job_id", "cancel_requested", "superseded", "retry_paused"):
                value = getattr(changes, name)
                if value is not None:
                    setattr(record.status, name, value)
            if changes.state is not None:
                record.status.state = (
                    "cancelling" if record.status.cancel_requested else changes.state
                )
            if not isinstance(changes.error, Unchanged):
                record.status.error = changes.error.model_copy(deep=True) if changes.error else None
            if changes.upstream_kind is not None:
                record.upstream_kind = changes.upstream_kind
            if changes.upstream_identity is not None:
                record.upstream_identity = changes.upstream_identity
            record.updated_at = time.time()
            self._write_record(record)
            return self.run(workspace_id, run_id)

    @staticmethod
    def _validate_page(
        record: RunRecord, outcomes: list[CompletedOutcome], cursor: int | None
    ) -> None:
        """Require contiguous, complete upstream checkpoints and consistent replay mappings."""
        if cursor is None:
            if any(o.service_cursor is not None for o in outcomes):
                raise AppError(
                    "SERVICE_INVALID_RESPONSE", "A service page requires a checkpoint", 502
                )
            return
        if cursor < 0 or cursor > len(record.service_indices):
            raise AppError("SERVICE_INVALID_RESPONSE", "Invalid service outcome cursor", 502)
        seen: list[int] = []
        for outcome in outcomes:
            source = outcome.service_cursor
            if (
                source is None
                or source < 1
                or source > cursor
                or outcome.index not in record.service_indices
            ):
                raise AppError("SERVICE_INVALID_RESPONSE", "Invalid service outcome mapping", 502)
            if source <= record.service_cursor:
                if record.service_outcomes.get(source) != outcome.index:
                    raise AppError(
                        "SERVICE_INVALID_RESPONSE", "Conflicting service outcome replay", 502
                    )
            else:
                seen.append(source)
        if seen != list(range(record.service_cursor + 1, cursor + 1)):
            raise AppError(
                "SERVICE_INVALID_RESPONSE", "Service page has missing or unordered outcomes", 502
            )

    def complete_outcomes(
        self,
        workspace_id: UUID,
        run_id: UUID,
        outcomes: list[CompletedOutcome],
        *,
        service_cursor: int | None = None,
        terminal_state: RunState | None = None,
        run_error: ErrorEnvelope | None = None,
    ) -> RunRecord:
        """Commit a complete page, results, cursors, and optional final state atomically.

        Args:
            workspace_id: Owner of the run.
            run_id: Comparison to update.
            outcomes: Completed scenarios, including source cursors for service pages.
            service_cursor: Upstream checkpoint represented by the entire page.
            terminal_state: Optional final state; all outcomes must then be complete.
            run_error: Optional final run-level error.

        Returns:
            A new snapshot after all writes succeed together.
        """
        with self._atomic():
            record = self.run(workspace_id, run_id)
            self._validate_page(record, outcomes, service_cursor)
            if record.status.state in TERMINAL:
                return record
            for incoming in outcomes:
                self._complete(record, incoming)
            if service_cursor is not None:
                record.service_cursor = max(record.service_cursor, service_cursor)
            if terminal_state is not None:
                if terminal_state not in TERMINAL or any(
                    not o.cursor for o in record.status.outcomes
                ):
                    raise AppError(
                        "SERVICE_INVALID_RESPONSE",
                        "Terminal run is missing completed outcomes",
                        502,
                    )
                record.status.state = terminal_state
                record.status.error = run_error.model_copy(deep=True) if run_error else None
                record.status.retry_paused = False
                record.reservation = 0
                self._finish_comparison(record)
            record.updated_at = time.time()
            self._write_record(record)
            return self.run(workspace_id, run_id)

    def _complete(self, record: RunRecord, incoming: CompletedOutcome) -> None:
        """Apply one validated completion inside its surrounding atomic operation."""
        if not 0 <= incoming.index < len(record.status.outcomes):
            raise AppError("SERVICE_INVALID_RESPONSE", "Invalid scenario outcome index", 502)
        outcome = record.status.outcomes[incoming.index]
        if outcome.cursor:
            if incoming.status != outcome.status or (
                incoming.service_cursor is not None
                and record.service_outcomes.get(incoming.service_cursor) != incoming.index
            ):
                raise AppError("SERVICE_INVALID_RESPONSE", "Conflicting scenario completion", 502)
            return
        if incoming.status not in (Status.SUCCEEDED, Status.FAILED, Status.CANCELLED):
            raise AppError("SERVICE_INVALID_RESPONSE", "Outcome is not final", 502)
        valid = (
            (
                incoming.status == Status.SUCCEEDED
                and incoming.result is not None
                and incoming.error is None
            )
            or (
                incoming.status == Status.FAILED
                and incoming.result is None
                and incoming.error is not None
            )
            or (
                incoming.status == Status.CANCELLED
                and incoming.result is None
                and incoming.error is None
            )
        )
        if not valid or (incoming.cached and incoming.status != Status.SUCCEEDED):
            raise AppError("SERVICE_INVALID_RESPONSE", "Invalid scenario result/error shape", 502)
        if incoming.result is not None:
            key = record.cache_keys[incoming.index]
            normalized = incoming.result.model_copy(update={"model_index": 0}, deep=True)
            if normalized.model != outcome.scenario.model:
                raise AppError(
                    "SERVICE_INVALID_RESPONSE",
                    "Result model differs from the submitted scenario",
                    502,
                )
            size = len(canonical(normalized.model_dump(mode="json")).encode())
            existing = self._blob_size(key)
            if existing is not None:
                # The execution key identifies an immutable result. Summaries must
                # describe the payload that is actually retained, not a caller's
                # different copy of the same execution.
                normalized = self._blob(key)
                size = existing
            if (
                size > self.settings.max_model_bytes
                or record.result_bytes + (existing or size) > self.settings.max_run_bytes
            ):
                raise AppError(
                    "RESULT_TOO_LARGE", "Model results exceed the configured storage limit", 422
                )
            if existing is None:
                if size > record.reservation:
                    raise AppError(
                        "RESULT_TOO_LARGE", "Run exceeded its reserved result budget", 422
                    )
                record.reservation -= size
                self._put_blob(key, normalized, size)
            record.result_bytes += existing if existing is not None else size
            record.results[outcome.scenario.id] = key
            outcome.loss_percent = loss_percent(
                sum(t.initial_value for t in record.task_set.tasks),
                normalized.summary_result.total_delivered_value,
            )
            outcome.completion_time = normalized.summary_result.completion_time
            outcome.delivered_value = normalized.summary_result.total_delivered_value
        outcome.status = incoming.status
        outcome.error = incoming.error.model_copy(deep=True) if incoming.error else None
        outcome.cached = incoming.cached
        record.status.last_cursor += 1
        outcome.cursor = record.status.last_cursor
        if incoming.service_cursor is not None:
            record.service_outcomes[incoming.service_cursor] = incoming.index

    def _finish_comparison(self, record: RunRecord) -> None:
        """Update comparison pointers together with a terminal run checkpoint."""
        workspace = self.get(record.workspace_id)
        if (
            any(o.status == Status.SUCCEEDED for o in record.status.outcomes)
            and not record.status.superseded
        ):
            if workspace.baseline_id is None and workspace.current_task_set == record.task_set.id:
                workspace.baseline_id = record.status.id
            if record.request.intent == "manual" and workspace.baseline_id != record.status.id:
                workspace.latest_id = record.status.id
        self._write_workspace(workspace)

    def cached_result(self, key: str) -> ResultData:
        """Return an independent reusable result or a structured missing error."""
        with self._atomic(False):
            if self._blob_size(key) is None:
                raise AppError("RESULT_NOT_FOUND", "This scenario has no completed result", 404)
            return self._blob(key)

    def result(self, record: RunRecord, scenario_id: UUID) -> ResultData:
        """Resolve a result from a frozen record, normalizing its scenario index."""
        key = record.results.get(scenario_id)
        if key is None:
            raise AppError("RESULT_NOT_FOUND", "This scenario has no completed result", 404)
        result = self.cached_result(key)
        index = next(
            i
            for i, outcome in enumerate(record.status.outcomes)
            if outcome.scenario.id == scenario_id
        )
        return result.model_copy(update={"model_index": index}, deep=True)

    def active_records(self) -> list[tuple[UUID, RunRecord]]:
        """Return owner identities and independent snapshots of active runs."""
        with self._atomic(False):
            return [(owner, self.run(owner, run_id)) for owner, run_id in self._records()]

    def comparison(self, workspace_id: UUID, run_id: UUID, action: str) -> Workspace:
        """Pin, unpin, restore a baseline, or explicitly delete a saved comparison."""
        with self._atomic():
            workspace = self.get(workspace_id)
            record = self.run(workspace_id, run_id)
            if record.status.state not in TERMINAL:
                raise AppError("RUN_ACTIVE", "Wait until the comparison finishes", 409)
            if action in {"pin", "baseline"} and not record.results:
                raise AppError("INVALID_INPUT", "A comparison needs at least one successful result")
            if action == "pin":
                if (
                    not record.status.pinned
                    and sum(r.pinned for r in workspace.runs) >= self.settings.max_pins
                ):
                    raise AppError(
                        "COMPARISON_LIMIT", "Unpin a comparison before pinning another", 409
                    )
                record.status.pinned = True
                self._write_record(record)
            elif action == "unpin":
                record.status.pinned = False
                self._write_record(record)
            elif action == "baseline":
                workspace.baseline_id = run_id
                workspace.current_task_set = record.task_set.id
                workspace.task_spec = record.task_set.spec.model_copy(deep=True)
                if (
                    workspace.latest_id
                    and self.run(workspace_id, workspace.latest_id).task_set.id
                    != record.task_set.id
                ):
                    workspace.latest_id = None
                workspace.revision += 1
            elif action == "delete":
                self._remove_run(run_id)
                if workspace.baseline_id == run_id:
                    workspace.baseline_id = None
                if workspace.latest_id == run_id:
                    workspace.latest_id = None
            else:
                raise AppError("INVALID_INPUT", "Unknown comparison action")
            self._write_workspace(workspace)
            self._collect_blobs()
            return self.get(workspace_id)

    def delete_workspace(self, workspace_id: UUID) -> None:
        """Explicitly delete saved workspace data when no run is active."""
        with self._atomic():
            workspace = self.get(workspace_id)
            if any(r.state not in TERMINAL for r in workspace.runs):
                raise AppError(
                    "RUN_ACTIVE", "Cancel active runs before deleting the workspace", 409
                )
            self._remove_workspace(workspace_id)
            self._collect_blobs()

    def delete_task_set(
        self, workspace_id: UUID, task_set_id: UUID, expected_revision: int
    ) -> None:
        """Explicitly delete an unused task set with a revision guard."""
        with self._atomic():
            workspace = self.get(workspace_id)
            if workspace.revision != expected_revision:
                raise AppError("REVISION_CONFLICT", "Reload before deleting this task set", 409)
            if task_set_id == workspace.current_task_set or any(
                r.task_set_id == task_set_id for r in workspace.runs
            ):
                raise AppError(
                    "REVISION_CONFLICT", "Task set is used by the editor or a comparison", 409
                )
            if not any(t.id == task_set_id for t in workspace.task_sets):
                raise AppError("RESULT_NOT_FOUND", "Task set not found", 404)
            workspace.task_sets = [t for t in workspace.task_sets if t.id != task_set_id]
            workspace.revision += 1
            self._write_workspace(workspace)


class InMemoryWorkspaceStore(WorkspaceOperations):
    """An isolated adapter implementing the same transactional snapshot contract."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        """Configure bounded in-memory storage for tests and explicit callers."""
        self.settings = settings or AppSettings()
        self.workspaces: dict[UUID, Workspace] = {}
        self.runs: dict[UUID, RunRecord] = {}
        self.cache: dict[str, tuple[ResultData, int]] = {}
        self._lock = RLock()

    @contextmanager
    def _atomic(self, write: bool = True) -> Iterator[None]:
        """Rollback metadata and immutable-result references if a write fails."""
        with self._lock:
            before = (
                (copy.deepcopy(self.workspaces), copy.deepcopy(self.runs), self.cache.copy())
                if write
                else None
            )
            try:
                yield
            except BaseException:
                if before is not None:
                    self.workspaces, self.runs, self.cache = before
                raise

    def _workspace(self, workspace_id: UUID) -> Workspace | None:
        """Assemble detached summaries without copying raw results."""
        stored = self.workspaces.get(workspace_id)
        if stored is None:
            return None
        workspace = stored.model_copy(deep=True)
        workspace.runs = [
            r.status.model_copy(deep=True)
            for r in self.runs.values()
            if r.workspace_id == workspace_id
        ]
        return workspace

    def _write_workspace(self, workspace: Workspace) -> None:
        """Store only editor/task state; run summaries come from run records."""
        self.workspaces[workspace.id] = workspace.model_copy(update={"runs": []}, deep=True)

    def _record(self, run_id: UUID) -> RunRecord | None:
        """Detach a stored record and all its nested mutable models."""
        return copy.deepcopy(self.runs.get(run_id))

    def _write_record(self, record: RunRecord) -> None:
        """Persist an independent run record."""
        self.runs[record.status.id] = copy.deepcopy(record)

    def _records(self) -> list[tuple[UUID, UUID]]:
        """List active owner/run identities in creation order."""
        return [
            (r.workspace_id, r.status.id)
            for r in self.runs.values()
            if r.status.state not in TERMINAL
        ]

    def _find_request(self, workspace_id: UUID, request_id: UUID) -> RunRecord | None:
        """Find a request without consulting a potentially stale caller snapshot."""
        return next(
            (
                copy.deepcopy(r)
                for r in self.runs.values()
                if r.workspace_id == workspace_id and r.request.request_id == request_id
            ),
            None,
        )

    def _blob_size(self, key: str) -> int | None:
        """Inspect immutable blob metadata."""
        return self.cache[key][1] if key in self.cache else None

    def _blob(self, key: str) -> ResultData:
        """Detach the requested raw result."""
        return self.cache[key][0].model_copy(deep=True)

    def _put_blob(self, key: str, result: ResultData, size: int) -> None:
        """Store a detached immutable result."""
        self.cache[key] = (result.model_copy(deep=True), size)

    def _usage(self) -> StorageUsage:
        """Count saved input, result, and reservation bytes."""
        inputs = sum(
            len(canonical(w.model_dump(mode="json", exclude={"runs"})).encode())
            for w in self.workspaces.values()
        )
        inputs += sum(
            len(canonical(r.status.model_dump(mode="json")).encode()) for r in self.runs.values()
        )
        return StorageUsage(
            len(self.workspaces),
            inputs,
            sum(size for _, size in self.cache.values()),
            sum(r.reservation for r in self.runs.values()),
            len(self._records()),
        )

    def _remove_run(self, run_id: UUID) -> None:
        """Delete a run only by explicit request."""
        del self.runs[run_id]

    def _remove_workspace(self, workspace_id: UUID) -> None:
        """Remove all workspace-owned records."""
        self.runs = {key: r for key, r in self.runs.items() if r.workspace_id != workspace_id}
        del self.workspaces[workspace_id]

    def _collect_blobs(self) -> None:
        """Preserve saved results and reusable results promised to active runs."""
        protect = {key for r in self.runs.values() for key in r.results.values()}
        protect.update(
            key
            for r in self.runs.values()
            if r.status.state not in TERMINAL
            for key in r.cache_keys
        )
        self.cache = {key: value for key, value in self.cache.items() if key in protect}

    def close(self) -> None:
        """No external resources are owned by this adapter."""

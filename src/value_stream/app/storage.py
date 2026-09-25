"""Replaceable, bounded workspace storage. Locks protect atomic mutations."""

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4
import time

from value_stream.service.schemas import ResultData
from .errors import AppError
from .generation import canonical, fingerprint, materialize_tasks, expand_scenarios
from .schemas import (
    Workspace,
    TaskSet,
    RunStatus,
    OutcomeSummary,
    TERMINAL,
    Preview,
    ENGINE_VERSION,
    GENERATOR_VERSION,
    RunRequest,
)
from .settings import AppSettings


@dataclass
class RunRecord:
    status: RunStatus
    task_set: TaskSet
    request: RunRequest
    request_hash: str
    cache_keys: list[str]
    results: dict[UUID, str] = field(default_factory=dict)
    service_indices: list[int] = field(default_factory=list)
    service_cursor: int = 0
    reservation: int = 0
    result_bytes: int = 0
    created_at: float = field(default_factory=time.monotonic)


class WorkspaceStore(Protocol):
    settings: AppSettings

    def create(self) -> Workspace: ...
    def get(self, workspace_id: UUID) -> Workspace: ...
    def run(self, workspace_id: UUID, run_id: UUID) -> RunRecord: ...
    def save_editor(self, workspace_id: UUID, request) -> Preview: ...
    def preview(self, workspace_id: UUID) -> Preview: ...
    def register(
        self, workspace_id: UUID, request, scenarios, task_set
    ) -> tuple[RunRecord, bool]: ...
    def retain_result(
        self, record: RunRecord, index: int, result: ResultData
    ) -> None: ...
    def previous(
        self, workspace: Workspace, request: RunRequest
    ) -> RunRecord | None: ...
    def cached_result(self, key: str) -> ResultData: ...
    def result(self, record: RunRecord, scenario_id: UUID) -> ResultData: ...
    def finish(self, workspace_id: UUID, record: RunRecord) -> None: ...
    def active_records(self) -> list[RunRecord]: ...
    def comparison(
        self, workspace_id: UUID, run_id: UUID, action: str
    ) -> Workspace: ...
    def delete_workspace(self, workspace_id: UUID) -> None: ...
    def delete_task_set(
        self, workspace_id: UUID, task_set_id: UUID, expected_revision: int
    ) -> None: ...


class InMemoryWorkspaceStore:
    def __init__(self, settings=None):
        self.settings = settings or AppSettings()
        self.workspaces: dict[UUID, Workspace] = {}
        self.runs: dict[UUID, RunRecord] = {}
        self.cache: OrderedDict[str, tuple[ResultData, int]] = OrderedDict()
        self.lock = RLock()

    def create(self):
        with self.lock:
            if len(self.workspaces) >= self.settings.max_workspaces:
                raise AppError(
                    "APP_CAPACITY",
                    "Workspace limit reached. Delete an unused workspace.",
                    429,
                )
            workspace = Workspace()
            self.workspaces[workspace.id] = workspace
            return workspace

    def get(self, workspace_id):
        try:
            return self.workspaces[workspace_id]
        except KeyError as exc:
            raise AppError(
                "WORKSPACE_NOT_FOUND",
                "This temporary workspace is unavailable. The server may have restarted.",
                404,
            ) from exc

    def run(self, workspace_id, run_id):
        w = self.get(workspace_id)
        if run_id not in {r.id for r in w.runs}:
            raise AppError("RUN_NOT_FOUND", "Run not found", 404)
        return self.runs[run_id]

    def delete_workspace(self, workspace_id):
        with self.lock:
            w = self.get(workspace_id)
            if any(r.state not in TERMINAL for r in w.runs):
                raise AppError(
                    "RUN_ACTIVE",
                    "Cancel active runs before deleting the workspace",
                    409,
                )
            for r in w.runs:
                self.runs.pop(r.id, None)
            del self.workspaces[workspace_id]
            self.prune_cache()

    def active_records(self):
        return [r for r in self.runs.values() if r.status.state not in TERMINAL]

    def cached_result(self, key):
        self.cache.move_to_end(key)
        return self.cache[key][0]

    def delete_task_set(self, workspace_id, task_set_id, expected_revision):
        with self.lock:
            w = self.get(workspace_id)
            if w.revision != expected_revision:
                raise AppError(
                    "REVISION_CONFLICT", "Reload before deleting this task set", 409
                )
            if task_set_id == w.current_task_set or any(
                r.task_set_id == task_set_id for r in w.runs
            ):
                raise AppError(
                    "REVISION_CONFLICT",
                    "Task set is used by the editor or a comparison",
                    409,
                )
            if not any(t.id == task_set_id for t in w.task_sets):
                raise AppError("RESULT_NOT_FOUND", "Task set not found", 404)
            w.task_sets = [t for t in w.task_sets if t.id != task_set_id]
            w.revision += 1

    def save_editor(self, workspace_id, request):
        with self.lock:
            w = self.get(workspace_id)
            if request.expected_revision != w.revision:
                raise AppError(
                    "REVISION_CONFLICT",
                    "Inputs changed in another tab. Reload the workspace.",
                    409,
                )
            if request.task_spec.count > self.settings.max_tasks:
                raise AppError(
                    "LIMIT_EXCEEDED", f"Task count exceeds {self.settings.max_tasks}"
                )
            if len({d.id for d in request.definitions}) != len(request.definitions):
                raise AppError("INVALID_INPUT", "Definition IDs must be unique")
            scenarios = expand_scenarios(request.definitions, self.settings)
            spec_hash = fingerprint(request.task_spec.model_dump())
            task_set = next(
                (
                    t
                    for t in w.task_sets
                    if fingerprint(t.spec.model_dump()) == spec_hash
                ),
                None,
            )
            if task_set is None:
                if len(w.task_sets) >= self.settings.max_task_sets:
                    raise AppError(
                        "APP_CAPACITY",
                        "Task-set limit reached. Remove unused task sets or start a new workspace.",
                        429,
                    )
                tasks = materialize_tasks(request.task_spec)
                task_set = TaskSet(
                    spec=request.task_spec.model_copy(deep=True),
                    tasks=tasks,
                    content_hash=fingerprint([t.model_dump() for t in tasks]),
                )
            candidate = w.model_copy()
            candidate.task_sets = list(w.task_sets)
            candidate.task_spec = request.task_spec.model_copy(deep=True)
            candidate.definitions = [
                d.model_copy(deep=True) for d in request.definitions
            ]
            if task_set.id not in {t.id for t in candidate.task_sets}:
                candidate.task_sets.append(task_set)
            candidate.current_task_set = task_set.id
            if w.current_task_set != task_set.id:
                candidate.baseline_id = candidate.latest_id = None
            candidate.revision += 1
            size = sum(
                self.input_size(other)
                for other in self.workspaces.values()
                if other.id != w.id
            ) + self.input_size(candidate)
            if size > self.settings.max_input_bytes:
                raise AppError("APP_CAPACITY", "Input storage limit reached", 429)
            self.workspaces[w.id] = candidate
            # Runs are shared immutable snapshots, not deep-copied mutable statuses.
            candidate.runs = [self.runs[r.id].status for r in w.runs]
            return self._preview(candidate, scenarios)

    @staticmethod
    def input_size(w):
        # Run summaries include their frozen model configurations, never raw results.
        return len(canonical(w.model_dump(mode="json")).encode())

    def _preview(self, w, scenarios):
        if w.current_task_set is None:
            raise AppError("INVALID_INPUT", "Save and preview inputs first")
        digest = fingerprint(
            [
                str(w.current_task_set),
                w.revision,
                [s.model_dump(mode="json") for s in scenarios],
            ]
        )
        return Preview(
            digest=digest,
            task_set_id=w.current_task_set,
            workspace_revision=w.revision,
            scenarios=scenarios,
            count=len(scenarios),
        )

    def preview(self, workspace_id):
        w = self.get(workspace_id)
        return self._preview(w, expand_scenarios(w.definitions, self.settings))

    def previous(self, w, request):
        hashed = fingerprint(request.model_dump(mode="json"))
        for status in w.runs:
            record = self.runs[status.id]
            if record.request.request_id == request.request_id:
                if record.request_hash != hashed:
                    raise AppError(
                        "SUBMISSION_CONFLICT",
                        "Request ID was used with different inputs",
                        409,
                    )
                return record
        return None

    def register(self, workspace_id, request, scenarios, task_set):
        with self.lock:
            w = self.get(workspace_id)
            previous = self.previous(w, request)
            if previous:
                return previous, False
            if any(r.state not in TERMINAL for r in w.runs):
                raise AppError(
                    "RUN_ACTIVE", "Cancel or finish the current run first", 409
                )
            if (
                sum(r.status.state not in TERMINAL for r in self.runs.values())
                >= self.settings.max_active_runs
            ):
                raise AppError(
                    "APP_CAPACITY", "All application execution slots are occupied", 429
                )
            if (
                request.intent == "interactive"
                and w.runs
                and time.monotonic() - self.runs[w.runs[-1].id].created_at
                < self.settings.min_interactive_seconds
            ):
                raise AppError(
                    "APP_CAPACITY",
                    "Wait a moment before the next interactive comparison",
                    429,
                )
            self.prune_history(w)
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
            missing = [i for i, key in enumerate(keys) if key not in self.cache]
            reservation = min(
                self.settings.max_run_bytes,
                self.settings.max_model_bytes * len(missing),
            )
            self.prune_cache(required=reservation, protect=set(keys))
            self.prune_for_capacity(reservation, set(keys))
            used = sum(v[1] for v in self.cache.values()) + sum(
                r.reservation for r in self.runs.values()
            )
            if used + reservation > self.settings.max_result_bytes:
                raise AppError(
                    "APP_CAPACITY",
                    "Result memory is full. Unpin or delete comparisons before running more models.",
                    429,
                )
            status = RunStatus(
                id=uuid4(),
                name=request.name,
                task_set_id=task_set.id,
                state="submitting",
                intent=request.intent,
                outcomes=[
                    OutcomeSummary(scenario=s.model_copy(deep=True)) for s in scenarios
                ],
            )
            record = RunRecord(
                status=status,
                task_set=task_set,
                request=request.model_copy(deep=True),
                request_hash=fingerprint(request.model_dump(mode="json")),
                cache_keys=keys,
                service_indices=missing,
                reservation=reservation,
            )
            input_bytes = sum(
                self.input_size(other) for other in self.workspaces.values()
            )
            if (
                input_bytes + len(status.model_dump_json().encode())
                > self.settings.max_input_bytes
            ):
                raise AppError(
                    "APP_CAPACITY",
                    "Input snapshot memory is full. Delete old comparisons.",
                    429,
                )
            self.runs[status.id] = record
            w.runs.append(status)
            if request.intent == "interactive":
                w.latest_id = status.id
            return record, True

    def retain_result(self, record, index, result):
        with self.lock:
            key = record.cache_keys[index]
            size = len(result.model_dump_json().encode())
            if (
                size > self.settings.max_model_bytes
                or record.result_bytes + size > self.settings.max_run_bytes
            ):
                raise AppError(
                    "RESULT_TOO_LARGE",
                    "Model results exceed the configured storage limit",
                    422,
                )
            if key not in self.cache:
                if size > record.reservation:
                    raise AppError(
                        "RESULT_TOO_LARGE", "Run exceeded its reserved result budget"
                    )
                record.reservation -= size
                self.cache[key] = (result, size)
            self.cache.move_to_end(key)
            record.result_bytes += size
            record.results[record.status.outcomes[index].scenario.id] = key

    def result(self, record, scenario_id):
        key = record.results.get(scenario_id)
        if key is None or key not in self.cache:
            raise AppError(
                "RESULT_NOT_FOUND", "This scenario has no completed result", 404
            )
        self.cache.move_to_end(key)
        return self.cache[key][0]

    def finish(self, workspace_id, record):
        record.reservation = 0
        w = self.get(workspace_id)
        if (
            any(o.status == "succeeded" for o in record.status.outcomes)
            and not record.status.superseded
        ):
            if w.baseline_id is None and w.current_task_set == record.task_set.id:
                w.baseline_id = record.status.id
            if record.request.intent == "manual" and w.baseline_id != record.status.id:
                w.latest_id = record.status.id

    def comparison(self, workspace_id, run_id, action):
        with self.lock:
            w = self.get(workspace_id)
            r = self.run(workspace_id, run_id)
            if r.status.state not in TERMINAL:
                raise AppError("RUN_ACTIVE", "Wait until the comparison finishes", 409)
            if action in {"pin", "baseline"} and not r.results:
                raise AppError(
                    "INVALID_INPUT", "A comparison needs at least one successful result"
                )
            if action == "pin":
                if (
                    not r.status.pinned
                    and sum(x.pinned for x in w.runs) >= self.settings.max_pins
                ):
                    raise AppError(
                        "COMPARISON_LIMIT",
                        "Unpin a comparison before pinning another",
                        409,
                    )
                r.status.pinned = True
            elif action == "unpin":
                r.status.pinned = False
            elif action == "baseline":
                w.baseline_id = run_id
                w.current_task_set = r.task_set.id
                w.task_spec = r.task_set.spec.model_copy(deep=True)
                if w.latest_id and self.runs[w.latest_id].task_set.id != r.task_set.id:
                    w.latest_id = None
                w.revision += 1
            elif action == "delete":
                w.runs = [x for x in w.runs if x.id != run_id]
                self.runs.pop(run_id)
                if w.baseline_id == run_id:
                    w.baseline_id = None
                if w.latest_id == run_id:
                    w.latest_id = None
                self.prune_cache()
            return w

    def prune_history(self, w):
        protected = {w.baseline_id, w.latest_id}
        for r in list(w.runs):
            if len(w.runs) < self.settings.max_retained_runs:
                break
            if r.state in TERMINAL and not r.pinned and r.id not in protected:
                w.runs.remove(r)
                self.runs.pop(r.id)
        if len(w.runs) >= self.settings.max_retained_runs:
            raise AppError(
                "APP_CAPACITY", "Run history is full. Delete a comparison.", 429
            )

    def prune_for_capacity(self, required, protect):
        def used():
            return sum(v[1] for v in self.cache.values()) + sum(
                r.reservation for r in self.runs.values()
            )

        candidates = sorted(
            [
                (w, status)
                for w in self.workspaces.values()
                for status in w.runs
                if status.state in TERMINAL
                and not status.pinned
                and status.id not in {w.baseline_id, w.latest_id}
            ],
            key=lambda pair: self.runs[pair[1].id].created_at,
        )
        for workspace, status in candidates:
            if used() + required <= self.settings.max_result_bytes:
                break
            workspace.runs.remove(status)
            self.runs.pop(status.id)
            self.prune_cache(required=required, protect=protect)

    def prune_cache(self, required=0, protect=None):
        references = {key for r in self.runs.values() for key in r.results.values()}
        active_keys = {
            key
            for r in self.runs.values()
            if r.status.state not in TERMINAL
            for key in r.cache_keys
        }
        used = sum(v[1] for v in self.cache.values()) + sum(
            r.reservation for r in self.runs.values()
        )
        for key in list(self.cache):
            if key not in references | active_keys | (protect or set()) and (
                required == 0 or used + required > self.settings.max_result_bytes
            ):
                used -= self.cache.pop(key)[1]

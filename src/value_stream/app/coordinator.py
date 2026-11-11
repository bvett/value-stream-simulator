"""Application run coordination, separate from routes and worker execution."""

import asyncio
import logging
import time
from uuid import uuid5, UUID
from typing import Literal
from value_stream.app.schemas import RunStatus
from value_stream.service.schemas import JobRequest, ErrorEnvelope
from .errors import AppError
from .generation import concrete_model, validate_model_limits
from .schemas import TERMINAL, ModelSettings, RunRequest, RunState, Status
from .storage import CompletedOutcome, RunChanges, WorkspaceStore, RunRecord, UpstreamKind
from .gateway import SimulationGateway

logger = logging.getLogger(__name__)


class RunCoordinator:
    """Coordinates workspace runs and communicates with the simulation service."""

    def __init__(
        self,
        store: WorkspaceStore,
        gateway: SimulationGateway,
        *,
        upstream_kind: UpstreamKind = "local",
        upstream_identity: str = "injected",
    ) -> None:
        """Configure run coordination with its workspace store and simulation gateway.

        Args:
            store (WorkspaceStore): Store used to retrieve or update data.
            gateway (SimulationGateway): Simulation service gateway.
            upstream_kind: Local ownership or an independent external service.
            upstream_identity: Stable database path or normalized configured URL.
        """
        self.store, self.gateway = store, gateway
        self.upstream_kind: UpstreamKind = upstream_kind
        self.upstream_identity = upstream_identity
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.closed = False

    async def start_run(self, workspace_id: UUID, request: RunRequest) -> RunStatus:
        """Start a run for the requested workspace scenarios.

        Args:
            workspace_id (UUID): Identifier of the workspace.
            request (RunRequest): Request data to process.

        Raises:
            AppError: If the service is unavailable, the request is invalid, or an active run
                conflicts with it.

        Returns:
            RunStatus: The resulting value.
        """

        if self.closed:
            raise AppError("SERVICE_UNAVAILABLE", "Application is shutting down", 503)
        w = self.store.get(workspace_id)
        previous = self.store.previous(w, request)
        if previous:
            return previous.status
        if request.intent == "interactive":
            if (
                request.source_run_id is None
                or request.property is None
                or request.property not in ModelSettings.model_fields.keys()
            ):
                raise AppError("INVALID_INPUT", "Choose a source comparison and a model property")
            source = self.store.run(workspace_id, request.source_run_id)
            if source.status.state not in TERMINAL or not source.results:
                raise AppError("INVALID_INPUT", "Interactive mode requires a completed comparison")
            if w.current_task_set != source.task_set.id:
                raise AppError(
                    "REVISION_CONFLICT",
                    "Interactive comparisons must use the current task set",
                    409,
                )
            scenarios = [
                o.scenario.model_copy(deep=True)
                for o in source.status.outcomes
                if (
                    request.definition_id is None
                    or o.scenario.definition_id == request.definition_id
                )
                and getattr(o.scenario.settings, request.property) == request.family_value
            ]
            if not scenarios:
                raise AppError(
                    "INVALID_INPUT",
                    "Select an existing value/family before changing it",
                )
            for scenario in scenarios:
                scenario.settings = ModelSettings.model_validate(
                    {**scenario.settings.model_dump(), request.property: request.value}
                )
                validate_model_limits(scenario.settings, self.store.settings)
                scenario.model = concrete_model(scenario.settings, scenario.team_seed)
                scenario.revision += 1
                scenario.name = (
                    f"{scenario.name.split(' → ')[0]} → {request.property}={request.value}"
                )
            task_set = source.task_set
            # Supersession is explicit and confirmed before replacement admission.
            active = next((r for r in w.runs if r.state not in TERMINAL), None)
            if active:
                if active.intent != "interactive":
                    raise AppError("RUN_ACTIVE", "Finish or cancel the manual run first", 409)
                self.store.patch_run(workspace_id, active.id, RunChanges(superseded=True))
                await self.cancel_run(workspace_id, active.id)
                raise AppError(
                    "RUN_ACTIVE",
                    "Waiting for the previous interactive job to stop",
                    409,
                )
        else:
            preview = self.store.preview(workspace_id)
            if preview.digest != request.preview_digest:
                raise AppError(
                    "REVISION_CONFLICT",
                    "Preview is stale. Preview the current inputs again.",
                    409,
                )
            scenarios = preview.scenarios
            task_set = next(t for t in w.task_sets if t.id == preview.task_set_id)
        record, created = self.store.register(workspace_id, request, scenarios, task_set)
        if created:
            record = self.store.patch_run(
                workspace_id,
                record.status.id,
                RunChanges(
                    upstream_kind=self.upstream_kind, upstream_identity=self.upstream_identity
                ),
            )
            record = self.launch(workspace_id, record)
        return record.status

    def launch(
        self, workspace_id: UUID, record: RunRecord, *, recovering: bool = False
    ) -> RunRecord:
        """Persist retry state before starting one poller for the stored run."""
        record = self.store.patch_run(
            workspace_id, record.status.id, RunChanges(retry_paused=False)
        )
        task = asyncio.create_task(self.execute(workspace_id, record, recovering=recovering))
        self.tasks[record.status.id] = task

        def forget(done: asyncio.Task[None]) -> None:
            """Do not remove a replacement poller when an older task exits."""
            if self.tasks.get(record.status.id) is done:
                self.tasks.pop(record.status.id, None)

        task.add_done_callback(forget)
        return record

    def recover(self) -> None:
        """Reconnect only known jobs belonging to the currently configured service."""
        for workspace_id, record in self.store.active_records():
            if record.status.job_id is None:
                self.finalize(workspace_id, record, "RUN_INTERRUPTED")
            elif (record.upstream_kind, record.upstream_identity) != (
                self.upstream_kind,
                self.upstream_identity,
            ):
                self.finalize(workspace_id, record, "SERVICE_CHANGED")
            else:
                self.launch(workspace_id, record, recovering=True)

    def finalize(
        self,
        workspace_id: UUID,
        record: RunRecord,
        code: Literal["SERVICE_CHANGED", "RUN_INTERRUPTED"],
    ) -> RunRecord:
        """Finalize missing outcomes while preserving every committed completion."""
        error = ErrorEnvelope(
            code=code,
            message={
                "SERVICE_CHANGED": "The configured simulation service changed. Completed results were retained.",
                "RUN_INTERRUPTED": "Application execution was interrupted. Completed results were retained.",
            }[code],
        )
        cancelled = code == "RUN_INTERRUPTED" and record.status.cancel_requested
        return self.store.complete_outcomes(
            workspace_id,
            record.status.id,
            [
                CompletedOutcome(
                    i,
                    Status.CANCELLED if cancelled else Status.FAILED,
                    error=None if cancelled else error,
                )
                for i, outcome in enumerate(record.status.outcomes)
                if not outcome.cursor
            ],
            terminal_state="cancelled" if cancelled else "failed",
            run_error=error,
        )

    async def poll(
        self, workspace_id: UUID, record: RunRecord, *, interrupted: bool = False
    ) -> RunRecord:
        """Drain one upstream page and commit results and its cursor together."""
        run_id, job_id = record.status.id, record.status.job_id
        if job_id is None:
            raise AppError("SERVICE_INVALID_RESPONSE", "Missing accepted service job", 502)
        if record.status.cancel_requested or interrupted:
            await self.gateway.cancel(job_id)
        upstream = await self.gateway.status(job_id)
        record = self.store.run(workspace_id, run_id)
        page = await self.gateway.outcomes(job_id, record.service_cursor)
        completed: list[CompletedOutcome] = []
        interrupted_outcome = False
        for outcome in page.outcomes:
            if outcome.model_index >= len(record.service_indices):
                raise AppError(
                    "SERVICE_INVALID_RESPONSE", "Service returned an invalid model index", 502
                )
            error = (
                ErrorEnvelope(code=outcome.error.code, message=outcome.error.message)
                if outcome.error
                else None
            )
            state = outcome.status
            local_interruption = self.upstream_kind == "local" and (
                (outcome.error is not None and outcome.error.code == "JOB_INTERRUPTED")
                or (interrupted and state == Status.CANCELLED)
            )
            if local_interruption:
                interrupted_outcome = True
                state = Status.CANCELLED if record.status.cancel_requested else Status.FAILED
                error = (
                    None
                    if record.status.cancel_requested
                    else ErrorEnvelope(
                        code="RUN_INTERRUPTED", message="Local simulation execution was interrupted"
                    )
                )
            completed.append(
                CompletedOutcome(
                    record.service_indices[outcome.model_index],
                    state,
                    outcome.result,
                    error,
                    service_cursor=outcome.cursor,
                )
            )
        terminal: RunState | None = upstream.status if upstream.status in TERMINAL else None
        # A prior page may already contain an interruption when the terminal status arrives.
        interrupted_outcome = interrupted_outcome or any(
            outcome.error is not None and outcome.error.code == "RUN_INTERRUPTED"
            for outcome in record.status.outcomes
        )
        run_error: ErrorEnvelope | None = None
        if terminal is not None and interrupted_outcome:
            terminal = "cancelled" if record.status.cancel_requested else "failed"
            run_error = ErrorEnvelope(
                code="RUN_INTERRUPTED", message="Local simulation execution was interrupted"
            )
        record = self.store.complete_outcomes(
            workspace_id,
            run_id,
            completed,
            service_cursor=page.next_cursor,
            terminal_state=terminal,
            run_error=run_error,
        )
        if record.status.state not in TERMINAL:
            record = self.store.patch_run(
                workspace_id, run_id, RunChanges(state=upstream.status, error=None)
            )
        return record

    async def execute(
        self, workspace_id: UUID, record: RunRecord, *, recovering: bool = False
    ) -> None:
        """Poll upstream work and commit complete outcome pages through the store.

        Args:
            workspace_id: Owner of the frozen run.
            record: Initial snapshot; stored state is reread after asynchronous calls.
            recovering: Poll an acknowledged job without submitting or rebuilding inputs.
        """
        run_id = record.status.id
        retry_start: float | None = None
        delay = self.store.settings.poll_seconds
        try:
            cached = [
                CompletedOutcome(i, Status.SUCCEEDED, self.store.cached_result(key), cached=True)
                for i, key in enumerate(record.cache_keys)
                if i not in record.service_indices and not record.status.outcomes[i].cursor
            ]
            record = self.store.complete_outcomes(
                workspace_id,
                run_id,
                cached,
                terminal_state="completed" if not record.service_indices else None,
            )
            if record.status.state in TERMINAL:
                return
            while True:
                record = self.store.run(workspace_id, run_id)
                if record.status.state in TERMINAL:
                    return
                try:
                    if record.status.job_id is None:
                        if recovering:
                            self.finalize(workspace_id, record, "RUN_INTERRUPTED")
                            return
                        request = JobRequest(
                            tasks=record.task_set.tasks,
                            models=[
                                record.status.outcomes[i].scenario.model
                                for i in record.service_indices
                            ],
                            model_seeds=[
                                record.status.outcomes[i].scenario.execution_seed
                                for i in record.service_indices
                            ],
                            submission_id=uuid5(run_id, "simulation"),
                        )
                        if (
                            len(request.model_dump_json().encode())
                            > self.store.settings.max_body_bytes
                        ):
                            raise AppError(
                                "BODY_TOO_LARGE",
                                "Expanded simulation request exceeds the body limit",
                                413,
                            )
                        await self.gateway.ready()
                        accepted = await self.gateway.submit(request)
                        record = self.store.patch_run(
                            workspace_id, run_id, RunChanges(job_id=accepted.job_id)
                        )
                    record = await self.poll(
                        workspace_id,
                        record,
                        interrupted=recovering and self.upstream_kind == "local",
                    )
                    if record.status.state in TERMINAL:
                        return
                    retry_start = None
                    delay = self.store.settings.poll_seconds
                except AppError as exc:
                    if exc.code != "SERVICE_UNAVAILABLE":
                        raise
                    self.store.patch_run(
                        workspace_id,
                        run_id,
                        RunChanges(
                            state="reconnecting", error=ErrorEnvelope.model_validate(exc.body())
                        ),
                    )
                    retry_start = retry_start if retry_start is not None else time.monotonic()
                    if time.monotonic() - retry_start >= self.store.settings.retry_seconds:
                        # Remove ownership before publishing the pause: an immediate
                        # resume may create a replacement poller synchronously.
                        if self.tasks.get(run_id) is asyncio.current_task():
                            self.tasks.pop(run_id)
                        self.store.patch_run(workspace_id, run_id, RunChanges(retry_paused=True))
                        return
                    delay = min(5, delay * 2)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Application run %s failed", run_id)
            failure = (
                exc
                if isinstance(exc, AppError)
                else AppError("INTERNAL_ERROR", "Unexpected application execution error", 500)
            )
            if failure.code == "JOB_NOT_FOUND":
                failure = AppError(
                    "SERVICE_JOB_LOST",
                    "The simulation job expired or the service restarted. Completed results "
                    "were retained.",
                    404,
                )
            record = self.store.run(workspace_id, run_id)
            if record.status.job_id is not None:
                try:
                    await self.gateway.cancel(record.status.job_id)
                except Exception:
                    logger.warning(
                        "Unable to confirm cancellation for job %s", record.status.job_id
                    )
            error = ErrorEnvelope.model_validate(failure.body())
            missing = [
                CompletedOutcome(i, Status.FAILED, error=error)
                for i, outcome in enumerate(record.status.outcomes)
                if not outcome.cursor
            ]
            self.store.complete_outcomes(
                workspace_id, run_id, missing, terminal_state="failed", run_error=error
            )

    async def cancel_run(self, workspace_id: UUID, run_id: UUID) -> RunStatus:
        """Persist cancellation intent without overwriting concurrent completions."""
        record = self.store.run(workspace_id, run_id)
        if record.status.state not in TERMINAL:
            record = self.store.patch_run(
                workspace_id, run_id, RunChanges(cancel_requested=True, state="cancelling")
            )
            if run_id not in self.tasks:
                record = self.launch(workspace_id, record)
        return record.status

    def resume(self, workspace_id: UUID, run_id: UUID) -> RunStatus:
        """Resume a paused poller from its latest committed checkpoint."""
        if self.closed:
            raise AppError("SERVICE_UNAVAILABLE", "Application is shutting down", 503)
        record = self.store.run(workspace_id, run_id)
        if record.status.state not in TERMINAL and run_id not in self.tasks:
            record = self.launch(workspace_id, record)
        return record.status

    async def close(self) -> None:
        """Detach external polling; drain and finalize owned-local work within five seconds."""
        self.closed = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.upstream_kind == "external":
            return

        async def drain(workspace_id: UUID, record: RunRecord) -> None:
            """Preserve service completions before marking missing local work interrupted."""
            if record.status.job_id is not None:
                try:
                    record = await self.poll(workspace_id, record, interrupted=True)
                except Exception:
                    logger.warning("Shutdown could not drain job %s", record.status.job_id)
            if record.status.state not in TERMINAL:
                self.finalize(workspace_id, record, "RUN_INTERRUPTED")

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(
                        drain(workspace_id, record)
                        for workspace_id, record in self.store.active_records()
                    )
                ),
                timeout=5,
            )
        except asyncio.TimeoutError:
            logger.warning("Shutdown drain timed out; retained runs will recover on startup")

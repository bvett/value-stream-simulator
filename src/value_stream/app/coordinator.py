"""Application run coordination, separate from routes and worker execution."""

from typing import Optional

import asyncio
import logging
import time
from uuid import uuid5, UUID
from value_stream.app.schemas import RunStatus
from value_stream.service.schemas import JobRequest, ErrorEnvelope, ResultData
from .errors import AppError
from .generation import concrete_model, validate_model_limits
from .metrics import loss_percent
from .schemas import TERMINAL, ModelSettings, RunRequest, Status
from .storage import WorkspaceStore, RunRecord
from .gateway import SimulationGateway

logger = logging.getLogger(__name__)


class RunCoordinator:
    """Coordinates workspace runs and communicates with the simulation service."""

    def __init__(self, store: WorkspaceStore, gateway: SimulationGateway) -> None:
        """Configure run coordination with its workspace store and simulation gateway.

        Args:
            store (WorkspaceStore): Store used to retrieve or update data.
            gateway (SimulationGateway): Simulation service gateway.
        """
        self.store, self.gateway = store, gateway
        self.tasks = {}
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
                active.superseded = True
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
            self.launch(workspace_id, record)
        return record.status

    def launch(self, workspace_id: UUID, record: RunRecord) -> None:
        """Launch execution of a simulation run.

        Args:
            workspace_id (UUID): Identifier of the workspace.
            record (RunRecord): Run record to update.
        """
        record.status.retry_paused = False
        task = asyncio.create_task(self.execute(workspace_id, record))
        self.tasks[record.status.id] = task
        task.add_done_callback(
            lambda done: (
                self.tasks.pop(record.status.id, None)
                if self.tasks.get(record.status.id) is done
                else None
            )
        )

    def complete_outcome(
        self,
        record: RunRecord,
        index: int,
        status: Status,
        result: Optional[ResultData] = None,
        error: ErrorEnvelope | None = None,
        cached: bool = False,
    ) -> None:
        """Record the completed scenario outcome.

        Args:
            record (RunRecord): Run record to update.
            index (int): Index of the scenario or model.
            status (Status): Current outcome status.
            result (Optional[ResultData]): Simulation result to retain.
            error (ErrorEnvelope | None): Optional error returned for the scenario.
            cached (bool): Whether the result came from the cache.
        """
        outcome = record.status.outcomes[index]
        if outcome.cursor:
            return
        if result is not None:
            self.store.retain_result(record, index, result)
            outcome.loss_percent = loss_percent(
                sum(t.initial_value for t in record.task_set.tasks),
                result.summary_result.total_delivered_value,
            )
            outcome.completion_time = result.summary_result.completion_time
            outcome.delivered_value = result.summary_result.total_delivered_value
        outcome.status, outcome.error, outcome.cached = status, error, cached
        record.status.last_cursor += 1
        outcome.cursor = record.status.last_cursor

    async def execute(self, workspace_id: UUID, record: RunRecord) -> None:
        """Execute the requested simulation operation.

        Args:
            workspace_id (UUID): Identifier of the workspace.
            record (RunRecord): Run record to update.

        Raises:
            AppError: If the simulation service rejects the job or cannot be reached.
        """
        status = record.status
        retry_start = None
        delay = self.store.settings.poll_seconds
        try:
            for i, key in enumerate(record.cache_keys):
                if i not in record.service_indices and not status.outcomes[i].cursor:
                    self.complete_outcome(
                        record,
                        i,
                        Status.SUCCEEDED,
                        self.store.cached_result(key),
                        cached=True,
                    )
            if not record.service_indices:
                status.state = "completed"
                self.store.finish(workspace_id, record)
                return
            request = JobRequest(
                tasks=record.task_set.tasks,
                models=[status.outcomes[i].scenario.model for i in record.service_indices],
                model_seeds=[
                    status.outcomes[i].scenario.execution_seed for i in record.service_indices
                ],
                submission_id=uuid5(status.id, "simulation"),
            )
            if len(request.model_dump_json().encode()) > self.store.settings.max_body_bytes:
                raise AppError(
                    "BODY_TOO_LARGE",
                    "Expanded simulation request exceeds the body limit",
                    413,
                )
            while status.state not in TERMINAL:
                try:
                    if status.job_id is None:
                        await self.gateway.ready()
                        accepted = await self.gateway.submit(request)
                        status.job_id = accepted.job_id
                    if status.cancel_requested:
                        status.state = "cancelling"
                        await self.gateway.cancel(status.job_id)
                    upstream = await self.gateway.status(status.job_id)
                    page = await self.gateway.outcomes(status.job_id, record.service_cursor)
                    for outcome in page.outcomes:
                        if outcome.cursor <= record.service_cursor:
                            continue
                        if outcome.model_index >= len(record.service_indices):
                            raise AppError(
                                "SERVICE_INVALID_RESPONSE",
                                "Service returned an invalid model index",
                                502,
                            )
                        i = record.service_indices[outcome.model_index]
                        error = (
                            ErrorEnvelope(code=outcome.error.code, message=outcome.error.message)
                            if outcome.error
                            else None
                        )
                        self.complete_outcome(record, i, outcome.status, outcome.result, error)
                    record.service_cursor = page.next_cursor
                    status.error = None
                    retry_start = None
                    delay = self.store.settings.poll_seconds
                    if upstream.status in {
                        "completed",
                        "completed_with_errors",
                        "cancelled",
                    }:
                        if any(not o.cursor for o in status.outcomes):
                            # Status and outcomes are separate reads; a terminal state must
                            # have a complete outcome set by the time the page is fetched.
                            raise AppError(
                                "SERVICE_INVALID_RESPONSE",
                                "Terminal job is missing outcomes",
                                502,
                            )
                        status.state = upstream.status
                        self.store.finish(workspace_id, record)
                        return
                    status.state = "cancelling" if status.cancel_requested else upstream.status
                except AppError as exc:
                    if exc.code != "SERVICE_UNAVAILABLE":
                        raise
                    status.state = "reconnecting"
                    status.error = ErrorEnvelope(**exc.body())
                    retry_start = retry_start or time.monotonic()
                    if time.monotonic() - retry_start >= self.store.settings.retry_seconds:
                        # Publish the pause only after the run can be relaunched.
                        # A caller may resume as soon as retry_paused becomes true.
                        if self.tasks.get(status.id) is asyncio.current_task():
                            self.tasks.pop(status.id)
                        status.retry_paused = True
                        return
                    delay = min(5, delay * 2)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Application run %s failed", status.id)
            error = (
                exc
                if isinstance(exc, AppError)
                else AppError("INTERNAL_ERROR", "Unexpected application execution error", 500)
            )
            if error.code == "JOB_NOT_FOUND":
                error = AppError(
                    "SERVICE_JOB_LOST",
                    "The simulation job expired or the service restarted. "
                    "Completed results were retained.",
                    404,
                )
            status.error = ErrorEnvelope(**error.body())
            if status.job_id:
                try:
                    await self.gateway.cancel(status.job_id)
                except Exception:
                    logger.warning("Unable to confirm cancellation for job %s", status.job_id)
            for i, o in enumerate(status.outcomes):
                if not o.cursor:
                    self.complete_outcome(record, i, Status.FAILED, error=status.error)
            status.state = "failed"
            self.store.finish(workspace_id, record)

    async def cancel_run(self, workspace_id: UUID, run_id: UUID) -> RunStatus:
        """Cancel a run that has not reached a terminal state.

        Args:
            workspace_id (UUID): Identifier of the workspace.
            run_id (UUID): Identifier of the simulation run.

        Returns:
            RunStatus: Updated status of the cancelled run.
        """
        record = self.store.run(workspace_id, run_id)
        if record.status.state not in TERMINAL:
            record.status.cancel_requested = True
            record.status.state = "cancelling"
            if run_id not in self.tasks:
                self.launch(workspace_id, record)
        return record.status

    def resume(self, workspace_id: UUID, run_id: UUID) -> RunStatus:
        """Resume a paused simulation run.

        Args:
            workspace_id (UUID): Identifier of the workspace.
            run_id (UUID): Identifier of the simulation run.

        Returns:
            RunStatus: Current status of the resumed run.
        """
        record = self.store.run(workspace_id, run_id)
        if record.status.state not in TERMINAL and run_id not in self.tasks:
            self.launch(workspace_id, record)
        return record.status

    async def close(self) -> None:
        """Close the client and release its resources."""
        self.closed = True

        async def cancel(record: RunRecord):
            if record.status.job_id:
                try:
                    await self.gateway.cancel(record.status.job_id)
                except Exception:
                    logger.warning(
                        "Shutdown could not confirm cancellation for %s",
                        record.status.job_id,
                    )

        try:
            await asyncio.wait_for(
                asyncio.gather(*(cancel(r) for r in self.store.active_records())),
                timeout=5,
            )
        except asyncio.TimeoutError:
            logger.warning("Shutdown cancellation timed out")
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

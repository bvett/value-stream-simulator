from typing import Optional
from pydantic import BaseModel, Field, PrivateAttr

from uuid import UUID

from .epoch import Epoch
from .event_status import EventStatus
from .task_event import TaskEvent
from .task_type import TaskType
from .task_state import TaskState


class TaskHistory(BaseModel):
    """Tracks task progress through a simulated workflow"""

    _events: list[TaskEvent] = PrivateAttr(default=[])
    epoch_start_sim_t: float = Field(default=0, ge=0)
    _epoch: Epoch = PrivateAttr(default_factory=lambda data: Epoch(data["epoch_start_sim_t"]))
    delivered_value: Optional[float] = Field(default=None)
    completed_story_points: float = Field(default=0)

    @property
    def epoch(self) -> Epoch:
        return self._epoch

    @property
    def events(self) -> list[TaskEvent]:
        return self._events

    def last_event(self) -> Optional[TaskEvent]:
        """Return the most recent event, or ``None`` when history is empty."""
        return None if not self.events else self.events[-1]

    def start(
        self,
        sim_time: float,
        event: TaskState,
        task_type: TaskType,
        is_rework: bool,
        resource_id: Optional[UUID] = None,
    ) -> None:
        """Append a start event to the task history.

        Args:
            sim_time (float): Simulation time of the event.
            event (TaskState): Workflow event to record.
            task_type (TaskType): Type of task being processed.
            is_rework (bool): Whether the task is rework.
            resource_id (Optional[UUID]): Identifier of the resource handling the task.

        Raises:
            ValueError: If time decreases, the task is already active, or it is terminal.
        """

        epoch_time = self.epoch.to_epoch_time(sim_time)

        last_event = self.last_event()

        if last_event is not None:
            if epoch_time < last_event.time:
                raise ValueError("Decreasing time value")

            if last_event.event_type == TaskEvent.EventType.TERMINAL:
                raise ValueError("Attempting to start a task from a terminal state")

            if (last_event.event_type == TaskEvent.EventType.START) and (
                last_event.status == EventStatus.SUCCESS
            ):
                raise ValueError("Attempt to start a task that is already started")

        self.events.append(
            TaskEvent.start(
                event=event,
                time=epoch_time,
                task_type=task_type,
                is_rework=is_rework,
                resource_id=resource_id,
            )
        )

    def end(
        self,
        sim_time: float,
        task_type: TaskType,
        is_rework: bool,
        event: Optional[TaskState] = None,
        status: EventStatus = EventStatus.SUCCESS,
        loss: float = 0,
        resource_id: Optional[UUID] = None,
    ) -> None:
        """Append an end event for the currently active task event.

        Args:
            sim_time (float): Simulation time of the event.
            task_type (TaskType): Type of task being processed.
            is_rework (bool): Whether the task is rework.
            event (Optional[TaskState]): Workflow event to record.
            status (EventStatus): Current outcome status.
            loss (float): Loss.
            resource_id (Optional[UUID]): Identifier of the resource handling the task.

        Raises:
            ValueError: If time decreases or no matching event is active.
        """

        epoch_time = self.epoch.to_epoch_time(sim_time)

        last_event = self.last_event()

        if (last_event is not None) and (epoch_time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None:

            if event is None:
                event = last_event.event

            if (
                (last_event.event_type == TaskEvent.EventType.START)
                and (last_event.status == EventStatus.SUCCESS)
                and (last_event.event == event)
            ):

                duration = epoch_time - last_event.time
                self.events.append(
                    TaskEvent.end(
                        event=event,
                        time=epoch_time,
                        status=status,
                        loss=loss,
                        task_type=task_type,
                        is_rework=is_rework,
                        duration=duration,
                        resource_id=resource_id,
                    )
                )
            else:
                raise ValueError("Attempting to end a task from an invalid state")

        else:
            raise ValueError("Attempting to end a task when there is no previous task history")

    def resume(self, event: TaskState) -> None:
        """Remove the matching end event so the task can resume.

        Args:
            event (TaskState): Event whose end record should be removed.

        Raises:
            ValueError: If history is empty or the last event does not match.
        """

        last_event = self.last_event()

        if last_event is None:
            raise ValueError("history is empty")

        if last_event.event_type != TaskEvent.EventType.END:
            raise ValueError("last event is not TypeEvent.EventType.END")

        if last_event.event != event:
            raise ValueError("last event is not " + str(event))

        del self.events[-1]

    def terminate(
        self,
        sim_time: float,
        event: TaskState,
        task_type: TaskType,
        is_rework: bool,
        status: EventStatus = EventStatus.SUCCESS,
        resource_id: Optional[UUID] = None,
    ) -> None:
        """Append a terminal event that prevents later events from starting.

        Args:
            sim_time (float): Simulation time of the event.
            event (TaskState): Workflow event to record.
            task_type (TaskType): Type of task being processed.
            is_rework (bool): Whether the task is rework.
            status (EventStatus): Current outcome status.
            resource_id (Optional[UUID]): Identifier of the resource handling the task.

        Raises:
            ValueError: If time decreases or the task is already terminal.
        """

        epoch_time = self.epoch.to_epoch_time(sim_time)

        last_event = self.last_event()

        if (last_event is not None) and (epoch_time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None and last_event.event_type == TaskEvent.EventType.TERMINAL:
            raise ValueError("Attempting to terminate a terminated task")

        self.events.append(
            TaskEvent.terminal(
                event=event,
                time=epoch_time,
                status=status,
                task_type=task_type,
                is_rework=is_rework,
                resource_id=resource_id,
            )
        )

from pydantic import BaseModel, Field

from typing import Optional
from uuid import UUID

from .epoch import Epoch
from .event_status import EventStatus
from .task_event import TaskEvent
from .task_type import TaskType
from .task_state import TaskState


class TaskHistory(BaseModel):
    """Tracks task progress through a simulated workflow"""

    events: list[TaskEvent] = Field(default=[], init=False)
    epoch_start_sim_t:  float = Field(default=0, ge=0)
    epoch: Epoch = Field(default_factory = lambda data: Epoch(data['epoch_start_sim_t']))
    delivered_value: Optional[float] = Field(default=None)
    completed_story_points: float = Field(default=0)

    def last_event(self):
        """Returns most recent event, or None if no events exist"""
        return None if not self.events else self.events[-1]

    def start(self, sim_time: float, event: TaskState, task_type: TaskType, is_rework: bool, resource_id: Optional[UUID] = None):
        """Starts an event

        Events must be empty, no events in progress, or not terminated
        """

        epoch_time = self.epoch.to_epoch_time(sim_time) #pylint: disable=E1101

        last_event = self.last_event()

        if last_event is not None:
            if epoch_time < last_event.time:
                raise ValueError("Decreasing time value")

            if last_event.event_type == TaskEvent.EventType.TERMINAL:
                raise ValueError(
                    "Attempting to start a task from a terminal state")

            if (last_event.event_type == TaskEvent.EventType.START) \
                    and (last_event.status == EventStatus.SUCCESS):
                raise ValueError(
                    "Attempt to start a task that is already started")

        # pylint: disable=E1101
        self.events.append(TaskEvent.start(
            event=event, time=epoch_time, task_type=task_type, is_rework=is_rework, resource_id=resource_id))  

    def end(self, sim_time: float, task_type: TaskType, is_rework: bool, event: Optional[TaskState] = None, status: EventStatus = EventStatus.SUCCESS, loss: float = 0, resource_id: Optional[UUID] = None):
        """Ends a started event"""

        epoch_time = self.epoch.to_epoch_time(sim_time) #pylint: disable=E1101

        last_event = self.last_event()

        if (last_event is not None) and (epoch_time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None:

            if event is None:
                event = last_event.event

            if (last_event.event_type == TaskEvent.EventType.START) \
                    and (last_event.status == EventStatus.SUCCESS) \
                    and (last_event.event == event):

                duration = epoch_time - last_event.time
                # pylint: disable=E1101
                self.events.append(TaskEvent.end(
                    event=event, time=epoch_time, status=status, loss=loss, task_type=task_type, is_rework=is_rework, duration=duration, resource_id=resource_id))
            else:
                raise ValueError(
                    "Attempting to end a task from an invalid state")

        else:
            raise ValueError(
                "Attempting to end a task when there is no previous task history")

    def resume(self, event: TaskState):
        """Removes the last event if event_type is END and matches event argument"""
        last_event = self.last_event()

        if last_event is None:
            raise ValueError("history is empty")

        if last_event.event_type != TaskEvent.EventType.END:
            raise ValueError("last event is not TypeEvent.EventType.END")

        if last_event.event != event:
            raise ValueError("last event is not " + str(event))

        del self.events[-1]

    def terminate(self, sim_time: float, event: TaskState, task_type: TaskType, is_rework: bool, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[UUID] = None):
        """Adds a terminal event to the history.

        A terminal event prevents additional events from being started"""

        epoch_time = self.epoch.to_epoch_time(sim_time) #pylint: disable=E1101

        last_event = self.last_event()

        if (last_event is not None) and (epoch_time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None and last_event.event_type == TaskEvent.EventType.TERMINAL:
            raise ValueError("Attempting to terminate a terminated task")

        # pylint: disable=E1101
        self.events.append(TaskEvent.terminal(
            event=event, time=epoch_time, status=status, task_type=task_type, is_rework=is_rework, resource_id=resource_id))

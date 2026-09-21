from enum import StrEnum
from pydantic import BaseModel, field_serializer
from typing import Optional
from uuid import UUID

from .event_status import EventStatus
from .task_type import TaskType
from .task_state import TaskState


class TaskEvent(BaseModel):
    """Records time-series metadata about a Task"""

    class EventType(StrEnum):
        """Defines whether event is part of a start/stop pair, or a singular terminal event"""
        START = 'start'
        END = 'end'
        TERMINAL = 'terminal'

    event : TaskState
    event_type : EventType
    time : float
    status : EventStatus
    loss : float = 0
    task_type : TaskType
    is_rework : bool
    duration : Optional[float] = None
    resource_id : Optional[UUID] = None

    @field_serializer('event')
    def serialize_event(self, event:TaskState):
        return event.value


    @classmethod
    def start(cls, event: TaskState, time: float, task_type: TaskType, is_rework: bool, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[UUID] = None) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.START, task_type=task_type, is_rework=is_rework, resource_id=resource_id)

    @classmethod
    def end(cls, event: TaskState, time: float, task_type: TaskType, is_rework: bool, duration: float, status: EventStatus = EventStatus.SUCCESS, loss: float = 0, resource_id: Optional[UUID] = None) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.END, loss=loss, task_type=task_type, is_rework=is_rework, duration=duration, resource_id=resource_id)

    @classmethod
    def terminal(cls, event: TaskState, time: float, task_type: TaskType, is_rework: bool, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[UUID] = None) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.TERMINAL, task_type=task_type, is_rework=is_rework, resource_id=resource_id)

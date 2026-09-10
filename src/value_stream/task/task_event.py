from enum import StrEnum
from typing import Optional
from uuid import UUID

from value_stream.core import WorkflowStateName
from .event_status import EventStatus
from .task_type import TaskType


class TaskEvent:
    """Records time-series metadata about a Task"""

    class EventType(StrEnum):
        """Defines whether event is part of a start/stop pair, or a singular terminal event"""
        START = 'start'
        END = 'end'
        TERMINAL = 'terminal'

    def __init__(self, event: WorkflowStateName, event_type: EventType, time: float, status: EventStatus, task_type: TaskType, is_rework: bool, duration: Optional[float] = None, loss: float = 0, resource_id: Optional[UUID] = None):
        self.event: WorkflowStateName = event
        self.event_type: TaskEvent.EventType = event_type
        self.time: float = time
        self.status: EventStatus = status
        self.loss: float = loss
        self.task_type: TaskType = task_type
        self.is_rework: bool = is_rework
        self.duration: Optional[float] = duration
        self.resource_id: Optional[UUID] = resource_id

    @classmethod
    def start(cls, event: WorkflowStateName, time: float, task_type: TaskType, is_rework: bool, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[UUID] = None) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.START, task_type=task_type, is_rework=is_rework, resource_id=resource_id)

    @classmethod
    def end(cls, event: WorkflowStateName, time: float, task_type: TaskType, is_rework: bool, duration: float, status: EventStatus = EventStatus.SUCCESS, loss: float = 0, resource_id: Optional[UUID] = None) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.END, loss=loss, task_type=task_type, is_rework=is_rework, duration=duration, resource_id=resource_id)

    @classmethod
    def terminal(cls, event: WorkflowStateName, time: float, task_type: TaskType, is_rework: bool, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[UUID] = None) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.TERMINAL, task_type=task_type, is_rework=is_rework, resource_id=resource_id)

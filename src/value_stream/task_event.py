from enum import StrEnum
from .workflow_state_name import WorkflowStateName


class TaskEvent:
    """Records time-series metadata about a Task"""

    class EventType(StrEnum):
        """Defines whether event is part of a start/stop pair, or a singular terminal event"""
        START = 'start'
        END = 'end'
        TERMINAL = 'terminal'

    class EventStatus(StrEnum):
        """Outcome status of the event."""
        SUCCESS = 'success'
        FAILURE = 'failure'

    def __init__(self, event: WorkflowStateName, event_type: EventType, time: float, status: EventStatus):
        self.event: WorkflowStateName = event
        self.event_type: TaskEvent.EventType = event_type
        self.time: float = time
        self.status: TaskEvent.EventStatus = status

    @classmethod
    def start(cls, event: WorkflowStateName, time: float, status: EventStatus = EventStatus.SUCCESS) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.START)

    @classmethod
    def end(cls, event: WorkflowStateName, time: float, status: EventStatus = EventStatus.SUCCESS) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.END)

    @classmethod
    def terminal(cls, event: WorkflowStateName, time: float, status: EventStatus = EventStatus.SUCCESS) -> "TaskEvent":
        return TaskEvent(event=event, time=time, status=status, event_type=TaskEvent.EventType.TERMINAL)

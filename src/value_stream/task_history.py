from .task_event import TaskEvent
from .workflow_state_name import WorkflowStateName


class TaskHistory():
    """Tracks task progress through a simulated workflow"""

    def __init__(self) -> None:
        self.events: list[TaskEvent] = []

    def last_event(self):
        return None if not self.events else self.events[-1]

    def start(self, event: WorkflowStateName, time: float):

        last_event = self.last_event()

        if last_event is not None:

            if time < last_event.time:
                raise ValueError("Decreasing time value")

            if last_event.event_type == TaskEvent.EventType.TERMINAL:
                raise ValueError(
                    "Attempting to start a task from a terminal state")

            if (last_event.event_type == TaskEvent.EventType.START) \
                    and (last_event.status == TaskEvent.EventStatus.SUCCESS):
                raise ValueError(
                    "Attempt to start a task that is already started")

        self.events.append(TaskEvent.start(event=event, time=time))

    def end(self, event: WorkflowStateName, time: float):

        last_event = self.last_event()

        if (last_event is not None) and (time < last_event.time):
            raise ValueError("Decreasing time value")

        if (last_event is not None) \
                and (last_event.event_type == TaskEvent.EventType.START) \
                and (last_event.status == TaskEvent.EventStatus.SUCCESS) \
                and (last_event.event == event):

            self.events.append(TaskEvent.end(event=event, time=time))

        else:
            raise ValueError("Attempting to end a task from an invalid state")

    def terminate(self, event: WorkflowStateName, time: float):

        last_event = self.last_event()

        if (last_event is not None) and (time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None and last_event.event_type == TaskEvent.EventType.TERMINAL:
            raise ValueError("Attempting to terminate a terminated task")

        self.events.append(TaskEvent.terminal(event=event, time=time))

    def event_times(self, event: WorkflowStateName) -> tuple[float, float]:
        """Returns the most recent start and end times of the event
        Returns as tuple (start_t, end_t)"""

        end_t = None
        start_t = None

        for e in reversed(self.events):
            if e.event == event:
                if e.event_type == TaskEvent.EventType.TERMINAL:
                    start_t = e.time
                    end_t = e.time

                if e.event_type == TaskEvent.EventType.END:
                    end_t = e.time

                if e.event_type == TaskEvent.EventType.START:
                    start_t = e.time

        if (start_t is None) or (end_t is None):
            raise ValueError(
                "Unable to find matching end and start times for event " + event)

        return (start_t, end_t)

    def duration(self, event: WorkflowStateName):
        """Returns the difference between the most recent end and start times for the event.
        Returns 0 for TERMINAL events"""

        start_t, end_t = self.event_times(event)

        return end_t - start_t

from .task_event import TaskEvent
from .workflow_state_name import WorkflowStateName


class TaskHistory():
    """Tracks task progress through a simulated workflow"""

    def __init__(self, baseline_time: float = 0) -> None:
        """Creates new object for tracking task history

        Args:
            baseline_time (float, optional): event timestamps will be relative to this value. Defaults to 0.
        """
        self.events: list[TaskEvent] = []
        self.baseline_t = baseline_time

    def last_event(self):
        """Returns most recent event, or None if no events exist"""
        return None if not self.events else self.events[-1]

    def start(self, time: float, event: WorkflowStateName):
        """Starts an event

        Events must be empty, no events in progress, or not terminated
        """

        time -= self.baseline_t

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

    def end(self, time: float, event: WorkflowStateName | None = None):
        """Ends a started event"""

        time -= self.baseline_t

        last_event = self.last_event()

        if (last_event is not None) and (time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None:

            if event is None:
                event = last_event.event

            if (last_event.event_type == TaskEvent.EventType.START) \
                    and (last_event.status == TaskEvent.EventStatus.SUCCESS) \
                    and (last_event.event == event):

                self.events.append(TaskEvent.end(event=event, time=time))
            else:
                raise ValueError(
                    "Attempting to end a task from an invalid state")

        else:
            raise ValueError(
                "Attempting to end a task when there is no previous task history")

    def resume(self, event: WorkflowStateName):
        """Removes the last event if event_type is END and matches event argument"""
        last_event = self.last_event()

        if last_event is None:
            raise ValueError("history is empty")

        if last_event.event_type != TaskEvent.EventType.END:
            raise ValueError("last event is not TypeEvent.EventType.END")

        if last_event.event != event:
            raise ValueError("last event is not " + event)

        del self.events[-1]

    def terminate(self, time: float, event: WorkflowStateName):
        """Adds a terminal event to the history.

        A terminal event prevents additional events from being started"""

        time -= self.baseline_t

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

from typing import Optional

from value_stream.core import EventStatus, WorkflowStateName

from .task_event import TaskEvent


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
                    and (last_event.status == EventStatus.SUCCESS):
                raise ValueError(
                    "Attempt to start a task that is already started")

        self.events.append(TaskEvent.start(event=event, time=time))

    def end(self, time: float, event: Optional[WorkflowStateName] = None, status: EventStatus = EventStatus.SUCCESS, loss: float = 0):
        """Ends a started event"""

        time -= self.baseline_t

        last_event = self.last_event()

        if (last_event is not None) and (time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None:

            if event is None:
                event = last_event.event

            if (last_event.event_type == TaskEvent.EventType.START) \
                    and (last_event.status == EventStatus.SUCCESS) \
                    and (last_event.event == event):

                self.events.append(TaskEvent.end(
                    event=event, time=time, status=status, loss=loss))
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

    def terminate(self, time: float, event: WorkflowStateName, status: EventStatus = EventStatus.SUCCESS):
        """Adds a terminal event to the history.

        A terminal event prevents additional events from being started"""

        time -= self.baseline_t

        last_event = self.last_event()

        if (last_event is not None) and (time < last_event.time):
            raise ValueError("Decreasing time value")

        if last_event is not None and last_event.event_type == TaskEvent.EventType.TERMINAL:
            raise ValueError("Attempting to terminate a terminated task")

        self.events.append(TaskEvent.terminal(
            event=event, time=time, status=status))

from value_stream.core import WorkflowStateName
from value_stream.task import TaskEvent, TaskHistory


class TestUtils:

    @classmethod
    def event_times(cls, history: TaskHistory, event: WorkflowStateName) -> tuple[float, float]:
        """Returns the most recent start and end times of the event
        Returns as tuple (start_t, end_t)"""

        end_t = None
        start_t = None

        for e in reversed(history.events):
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

    @classmethod
    def duration(cls, history: TaskHistory, event: WorkflowStateName):
        """Returns the difference between the most recent end and start times for the event.
        Returns 0 for TERMINAL events"""

        start_t, end_t = cls.event_times(history, event)

        return end_t - start_t

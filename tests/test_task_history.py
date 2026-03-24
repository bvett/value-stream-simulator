import unittest

from value_stream import TaskHistory, TaskEvent, WorkflowStateName

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestTaskHistory(unittest.TestCase):

    def setUp(self):
        self.history = TaskHistory()

    def test_start(self):
        # Happy path
        self.history.start(10, WorkflowStateName.DEVELOPMENT)

        self.assertEqual(len(self.history.events), 1)

        start_event = self.history.events[0]

        self.assertEqual(start_event.event, WorkflowStateName.DEVELOPMENT)
        self.assertEqual(start_event.event_type, TaskEvent.EventType.START)
        self.assertEqual(start_event.time, 10)
        self.assertEqual(start_event.status, TaskEvent.EventStatus.SUCCESS)

        # Error Handling

        # Time is earlier than previous event
        with self.assertRaises(ValueError):
            self.history.start(9, WorkflowStateName.DEVELOPMENT)

        # Starting an event before prior ended
        with self.assertRaises(ValueError):
            self.history.start(10, WorkflowStateName.DEVELOPMENT)

        # Starting nested event of same type
        with self.assertRaises(ValueError):
            self.history.start(10, WorkflowStateName.DEPLOYMENT)

        # Start after previous event ended
        self.history.end(time=15, event=WorkflowStateName.DEVELOPMENT)
        self.history.start(16, WorkflowStateName.DEVELOPMENT)

        self.assertEqual(len(self.history.events), 3)

    def test_end(self):

        # ending w/o corresponding start:
        with self.assertRaises(ValueError):
            self.history.end(time=10, event=WorkflowStateName.DEVELOPMENT)

        self.history.start(10, WorkflowStateName.DEVELOPMENT)

        # decreasing time
        with self.assertRaises(ValueError):
            self.history.end(time=9, event=WorkflowStateName.DEVELOPMENT)

        # mismatch between start/end events
        with self.assertRaises(ValueError):
            self.history.end(time=11, event=WorkflowStateName.DEPLOYMENT)

        # Happy path
        self.history.end(time=10, event=WorkflowStateName.DEVELOPMENT)

        self.assertEqual(len(self.history.events), 2)

        end_event = self.history.events[1]

        self.assertEqual(end_event.event, WorkflowStateName.DEVELOPMENT)
        self.assertEqual(end_event.event_type, TaskEvent.EventType.END)
        self.assertEqual(end_event.time, 10)
        self.assertEqual(end_event.status, TaskEvent.EventStatus.SUCCESS)

    def test_end_with_default_event(self):
        self.history.start(10, WorkflowStateName.PENDING)
        self.history.end(time=10)

        end_event = self.history.events[1]

        self.assertEqual(end_event.event, WorkflowStateName.PENDING)
        self.assertEqual(end_event.event_type, TaskEvent.EventType.END)
        self.assertEqual(end_event.time, 10)
        self.assertEqual(end_event.status, TaskEvent.EventStatus.SUCCESS)

    def test_terminate(self):
        # test attempts to start/end after terminate

        with self.assertRaises(ValueError):
            self.history.start(1, WorkflowStateName.DEVELOPMENT)
            self.history.terminate(2, WorkflowStateName.DELIVERY)
            self.history.end(time=3, event=WorkflowStateName.DEVELOPMENT)

        # terminate right away
        history = TaskHistory()
        history.terminate(1, WorkflowStateName.DELIVERY)

        with self.assertRaises(ValueError):
            history.terminate(2, WorkflowStateName.DELIVERY)

        with self.assertRaises(ValueError):
            history.start(2, WorkflowStateName.DEVELOPMENT)

        with self.assertRaises(ValueError):
            history.end(time=2, event=WorkflowStateName.DEVELOPMENT)

        with self.assertRaises(ValueError):
            history.terminate(0, WorkflowStateName.DELIVERY)

        self.assertEqual(len(history.events), 1)

        terminal_event = history.events[-1]

        self.assertEqual(terminal_event.event, WorkflowStateName.DELIVERY)
        self.assertEqual(terminal_event.event_type,
                         TaskEvent.EventType.TERMINAL)
        self.assertEqual(terminal_event.time, 1)
        self.assertEqual(terminal_event.status, TaskEvent.EventStatus.SUCCESS)

    def test_resume(self):

        # resume an empty history

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.resume(WorkflowStateName.DEVELOPMENT)

        # resume in-progress event

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.start(1, WorkflowStateName.PENDING)
            history.resume(WorkflowStateName.PENDING)

        # resume terminated event

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.terminate(1, WorkflowStateName.DELIVERY)
            history.resume(WorkflowStateName.DELIVERY)

        # resume with mismatched event type

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.start(1, WorkflowStateName.DEVELOPMENT)
            history.end(2, WorkflowStateName.DEVELOPMENT)
            history.resume(WorkflowStateName.DEPLOYMENT)

        # happy path:

        history = TaskHistory()

        history.start(1, WorkflowStateName.DEVELOPMENT)
        history.end(5, WorkflowStateName.DEVELOPMENT)

        self.assertEqual(history.duration(WorkflowStateName.DEVELOPMENT), 4)

        history.resume(WorkflowStateName.DEVELOPMENT)
        history.end(9, WorkflowStateName.DEVELOPMENT)

        self.assertEqual(history.duration(WorkflowStateName.DEVELOPMENT), 8)

    def test_event_times(self):
        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.event_times(WorkflowStateName.PENDING)

        history.start(1, WorkflowStateName.PENDING)

        with self.assertRaises(ValueError):
            history.event_times(WorkflowStateName.PENDING)

        history.end(time=2, event=WorkflowStateName.PENDING)

        with self.assertRaises(ValueError):
            history.event_times(WorkflowStateName.DEVELOPMENT)

        start, end = history.event_times(WorkflowStateName.PENDING)
        self.assertEqual(start, 1)
        self.assertEqual(end, 2)

        history.terminate(3, WorkflowStateName.DELIVERY)

        start, end = history.event_times(WorkflowStateName.DELIVERY)

        self.assertEqual(end-start, 0)

    def test_duration(self):
        self.history.start(3, WorkflowStateName.DEV_COMPLETE)
        self.history.end(time=7, event=WorkflowStateName.DEV_COMPLETE)

        self.assertEqual(self.history.duration(
            WorkflowStateName.DEV_COMPLETE), 4)

        self.history.start(10, WorkflowStateName.DEPLOYMENT)

        with self.assertRaises(ValueError):
            self.history.duration(WorkflowStateName.DEPLOYMENT)

import unittest

from value_stream import TaskHistory, TaskEvent, WorkflowStateName

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestTaskHistory(unittest.TestCase):

    def setUp(self):
        self.history = TaskHistory()

    def test_start(self):
        # Happy path
        self.history.start(WorkflowStateName.DEVELOPMENT, time=10)

        self.assertEqual(len(self.history.events), 1)

        start_event = self.history.events[0]

        self.assertEqual(start_event.event, WorkflowStateName.DEVELOPMENT)
        self.assertEqual(start_event.event_type, TaskEvent.EventType.START)
        self.assertEqual(start_event.time, 10)
        self.assertEqual(start_event.status, TaskEvent.EventStatus.SUCCESS)

        # Error Handling

        # Time is earlier than previous event
        with self.assertRaises(ValueError):
            self.history.start(WorkflowStateName.DEVELOPMENT, time=9)

        # Starting an event before prior ended
        with self.assertRaises(ValueError):
            self.history.start(WorkflowStateName.DEVELOPMENT, time=10)

        # Starting nested event of same type
        with self.assertRaises(ValueError):
            self.history.start(WorkflowStateName.DEPLOYMENT, time=10)

        # Start after previous event ended
        self.history.end(WorkflowStateName.DEVELOPMENT, time=15)
        self.history.start(WorkflowStateName.DEVELOPMENT, time=16)

        self.assertEqual(len(self.history.events), 3)

    def test_end(self):

        # ending w/o corresponding start:
        with self.assertRaises(ValueError):
            self.history.end(WorkflowStateName.DEVELOPMENT, time=10)

        self.history.start(WorkflowStateName.DEVELOPMENT, time=10)

        # decreasing time
        with self.assertRaises(ValueError):
            self.history.end(WorkflowStateName.DEVELOPMENT, time=9)

        # mismatch between start/end events
        with self.assertRaises(ValueError):
            self.history.end(WorkflowStateName.DEPLOYMENT, time=11)

        # Happy path
        self.history.end(WorkflowStateName.DEVELOPMENT, time=10)

        self.assertEqual(len(self.history.events), 2)

        end_event = self.history.events[1]

        self.assertEqual(end_event.event, WorkflowStateName.DEVELOPMENT)
        self.assertEqual(end_event.event_type, TaskEvent.EventType.END)
        self.assertEqual(end_event.time, 10)
        self.assertEqual(end_event.status, TaskEvent.EventStatus.SUCCESS)

    def test_terminate(self):
        # test attempts to start/end after terminate

        with self.assertRaises(ValueError):
            self.history.start(WorkflowStateName.DEVELOPMENT, time=1)
            self.history.terminate(WorkflowStateName.DELIVERY, time=2)
            self.history.end(WorkflowStateName.DEVELOPMENT, time=3)

        # terminate right away
        history = TaskHistory()
        history.terminate(WorkflowStateName.DELIVERY, time=1)

        with self.assertRaises(ValueError):
            history.terminate(WorkflowStateName.DELIVERY, time=2)

        with self.assertRaises(ValueError):
            history.start(WorkflowStateName.DEVELOPMENT, time=2)

        with self.assertRaises(ValueError):
            history.end(WorkflowStateName.DEVELOPMENT, time=2)

        with self.assertRaises(ValueError):
            history.terminate(WorkflowStateName.DELIVERY, time=0)

        self.assertEqual(len(history.events), 1)

        terminal_event = history.events[-1]

        self.assertEqual(terminal_event.event, WorkflowStateName.DELIVERY)
        self.assertEqual(terminal_event.event_type,
                         TaskEvent.EventType.TERMINAL)
        self.assertEqual(terminal_event.time, 1)
        self.assertEqual(terminal_event.status, TaskEvent.EventStatus.SUCCESS)

    def test_event_times(self):
        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.event_times(WorkflowStateName.PENDING)

        history.start(WorkflowStateName.PENDING, time=1)

        with self.assertRaises(ValueError):
            history.event_times(WorkflowStateName.PENDING)

        history.end(WorkflowStateName.PENDING, time=2)

        with self.assertRaises(ValueError):
            history.event_times(WorkflowStateName.DEVELOPMENT)

        start, end = history.event_times(WorkflowStateName.PENDING)
        self.assertEqual(start, 1)
        self.assertEqual(end, 2)

        history.terminate(WorkflowStateName.DELIVERY, time=3)

        start, end = history.event_times(WorkflowStateName.DELIVERY)

        self.assertEqual(end-start, 0)

    def test_duration(self):
        self.history.start(WorkflowStateName.DEV_COMPLETE, time=3)
        self.history.end(WorkflowStateName.DEV_COMPLETE, time=7)

        self.assertEqual(self.history.duration(
            WorkflowStateName.DEV_COMPLETE), 4)

        self.history.start(WorkflowStateName.DEPLOYMENT, time=10)

        with self.assertRaises(ValueError):
            self.history.duration(WorkflowStateName.DEPLOYMENT)

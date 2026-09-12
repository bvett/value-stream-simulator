import unittest

from value_stream.task import EventStatus, TaskHistory, TaskEvent, TaskType
from value_stream.workflow import SDLCWorkflow

from ..testutils import TestUtils

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestTaskHistory(unittest.TestCase, TestUtils):

    def setUp(self):
        self.history = TaskHistory()

    def test_start(self):
        # Happy path
        self.history.start(10, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(len(self.history.events), 1)

        start_event = self.history.events[0]

        self.assertEqual(start_event.event,
                         SDLCWorkflow.WorkflowState.DEVELOPMENT)
        self.assertEqual(start_event.event_type, TaskEvent.EventType.START)
        self.assertEqual(start_event.time, 10)
        self.assertEqual(start_event.status, EventStatus.SUCCESS)

        # Error Handling

        # Time is earlier than previous event
        with self.assertRaises(ValueError):
            self.history.start(9, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                               task_type=TaskType.DEVELOPMENT, is_rework=False)

        # Starting an event before prior ended
        with self.assertRaises(ValueError):
            self.history.start(10, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                               task_type=TaskType.DEVELOPMENT, is_rework=False)

        # Starting nested event of same type
        with self.assertRaises(ValueError):
            self.history.start(10, SDLCWorkflow.WorkflowState.DEPLOYMENT,
                               task_type=TaskType.DEVELOPMENT, is_rework=False)

        # Start after previous event ended
        self.history.end(sim_time=15, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.start(16, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(len(self.history.events), 3)

    def test_end(self):

        # ending w/o corresponding start:
        with self.assertRaises(ValueError):
            self.history.end(sim_time=10, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                             task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.history.start(10, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)

        # decreasing time
        with self.assertRaises(ValueError):
            self.history.end(sim_time=9, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                             task_type=TaskType.DEVELOPMENT, is_rework=False)

        # mismatch between start/end events
        with self.assertRaises(ValueError):
            self.history.end(sim_time=11, event=SDLCWorkflow.WorkflowState.DEPLOYMENT,
                             task_type=TaskType.DEVELOPMENT, is_rework=False)

        # Happy path
        self.history.end(sim_time=10, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(len(self.history.events), 2)

        end_event = self.history.events[1]

        self.assertEqual(
            end_event.event, SDLCWorkflow.WorkflowState.DEVELOPMENT)
        self.assertEqual(end_event.event_type, TaskEvent.EventType.END)
        self.assertEqual(end_event.time, 10)
        self.assertEqual(end_event.status, EventStatus.SUCCESS)

    def test_end_with_default_event(self):
        self.history.start(10, SDLCWorkflow.WorkflowState.PENDING,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.end(sim_time=10,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)

        end_event = self.history.events[1]

        self.assertEqual(end_event.event, SDLCWorkflow.WorkflowState.PENDING)
        self.assertEqual(end_event.event_type, TaskEvent.EventType.END)
        self.assertEqual(end_event.time, 10)
        self.assertEqual(end_event.status, EventStatus.SUCCESS)

    def test_terminate(self):
        # test attempts to start/end after terminate

        with self.assertRaises(ValueError):
            self.history.start(1, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                               task_type=TaskType.DEVELOPMENT, is_rework=False)
            self.history.terminate(2, SDLCWorkflow.WorkflowState.DELIVERY,
                                   task_type=TaskType.DEVELOPMENT, is_rework=False)
            self.history.end(sim_time=3, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                             task_type=TaskType.DEVELOPMENT, is_rework=False)

        # terminate right away
        history = TaskHistory()
        history.terminate(1, SDLCWorkflow.WorkflowState.DELIVERY,
                          task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            history.terminate(2, SDLCWorkflow.WorkflowState.DELIVERY,
                              task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            history.start(2, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                          task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            history.end(sim_time=2, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                        task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            history.terminate(0, SDLCWorkflow.WorkflowState.DELIVERY,
                              task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(len(history.events), 1)

        terminal_event = history.events[-1]

        self.assertEqual(terminal_event.event,
                         SDLCWorkflow.WorkflowState.DELIVERY)
        self.assertEqual(terminal_event.event_type,
                         TaskEvent.EventType.TERMINAL)
        self.assertEqual(terminal_event.time, 1)
        self.assertEqual(terminal_event.status, EventStatus.SUCCESS)

    def test_resume(self):

        # resume an empty history

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.resume(SDLCWorkflow.WorkflowState.DEVELOPMENT)

        # resume in-progress event

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.start(1, SDLCWorkflow.WorkflowState.PENDING,
                          task_type=TaskType.DEVELOPMENT, is_rework=False)
            history.resume(SDLCWorkflow.WorkflowState.PENDING)

        # resume terminated event

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.terminate(1, SDLCWorkflow.WorkflowState.DELIVERY,
                              task_type=TaskType.DEVELOPMENT, is_rework=False)
            history.resume(SDLCWorkflow.WorkflowState.DELIVERY)

        # resume with mismatched event type

        history = TaskHistory()

        with self.assertRaises(ValueError):
            history.start(1, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                          task_type=TaskType.DEVELOPMENT, is_rework=False)
            history.end(2, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                        task_type=TaskType.DEVELOPMENT, is_rework=False)
            history.resume(SDLCWorkflow.WorkflowState.DEPLOYMENT)

        # happy path:

        history = TaskHistory()

        history.start(1, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                      task_type=TaskType.DEVELOPMENT, is_rework=False)
        history.end(5, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                    task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(self.duration(
            history, SDLCWorkflow.WorkflowState.DEVELOPMENT), 4)

        history.resume(SDLCWorkflow.WorkflowState.DEVELOPMENT)
        history.end(9, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                    task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(self.duration(
            history, SDLCWorkflow.WorkflowState.DEVELOPMENT), 8)

    def test_event_times(self):
        history = TaskHistory()

        with self.assertRaises(ValueError):
            self.event_times(history, SDLCWorkflow.WorkflowState.PENDING)

        history.start(1, SDLCWorkflow.WorkflowState.PENDING,
                      task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            self.event_times(history, SDLCWorkflow.WorkflowState.PENDING)

        history.end(sim_time=2, event=SDLCWorkflow.WorkflowState.PENDING,
                    task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            self.event_times(history, SDLCWorkflow.WorkflowState.DEVELOPMENT)

        start, end = self.event_times(
            history, SDLCWorkflow.WorkflowState.PENDING)
        self.assertEqual(start, 1)
        self.assertEqual(end, 2)

        history.terminate(3, SDLCWorkflow.WorkflowState.DELIVERY,
                          task_type=TaskType.DEVELOPMENT, is_rework=False)

        start, end = self.event_times(
            history, SDLCWorkflow.WorkflowState.DELIVERY)

        self.assertEqual(end-start, 0)

    def test_duration(self):
        self.history.start(3, SDLCWorkflow.WorkflowState.DEV_COMPLETE,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.end(sim_time=7, event=SDLCWorkflow.WorkflowState.DEV_COMPLETE,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)

        self.assertEqual(self.duration(
            self.history, SDLCWorkflow.WorkflowState.DEV_COMPLETE), 4)

        self.history.start(10, SDLCWorkflow.WorkflowState.DEPLOYMENT,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)

        with self.assertRaises(ValueError):
            self.duration(self.history, SDLCWorkflow.WorkflowState.DEPLOYMENT)

    def test_recurrence(self):
        # Ensure the same workflow state can be represented multiple times
        self.history.start(0, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.end(1.0, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.start(1.0, SDLCWorkflow.WorkflowState.QA_TESTING,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.end(2.0, event=SDLCWorkflow.WorkflowState.QA_TESTING,
                         status=EventStatus.FAILURE,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.start(2.0, SDLCWorkflow.WorkflowState.DEVELOPMENT,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.end(3.0, event=SDLCWorkflow.WorkflowState.DEVELOPMENT,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.start(3.0, SDLCWorkflow.WorkflowState.QA_TESTING,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.end(4.0, event=SDLCWorkflow.WorkflowState.QA_TESTING,
                         task_type=TaskType.DEVELOPMENT, is_rework=False)
        self.history.start(4.0, SDLCWorkflow.WorkflowState.QA_COMPLETE,
                           task_type=TaskType.DEVELOPMENT, is_rework=False)

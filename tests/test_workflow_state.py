import unittest

from simpy import Environment, Event

from value_stream import Task, TaskEvent
from value_stream.workflow_state import WorkflowState, TerminalWorkflowState

from value_stream.workflow_state_name import WorkflowStateName

# pylint: disable=missing-class-docstring,missing-function-docstring


class TestWorkflowState(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.state = WorkflowState(self.env, WorkflowStateName.DEVELOPMENT)
        self.terminal_state = TerminalWorkflowState(
            self.env, WorkflowStateName.DELIVERY)

    def test_put(self):
        task = Task(initial_value=50.0, complexity=1.0, creation_time=0)

        self.assertEqual(len(self.state.items), 0)
        self.env.run(until=1)

        self.state.put(task)
        self.assertEqual(len(self.state.items), 1)

        self.assertEqual(task.delivered_value, 0)

        self.assertEqual(len(task.history.events), 1)

        event = task.history.events[0]

        self.assertEqual(event.time, self.env.now)
        self.assertEqual(event.event, self.state.name)
        self.assertEqual(event.event_type, TaskEvent.EventType.START)
        self.assertEqual(event.status, TaskEvent.EventStatus.SUCCESS)

    def test_put_terminal(self):
        task = Task(initial_value=50.0, complexity=1.0,
                    creation_time=0, depreciation_rate=0.1)

        self.assertEqual(len(self.state.items), 0)
        self.env.run(until=1)

        self.terminal_state.put(task)
        self.assertEqual(len(self.terminal_state.items), 1)

        self.assertEqual(task.delivered_value, 45.0)

        self.assertEqual(len(task.history.events), 1)

        event = task.history.events[0]

        self.assertEqual(event.time, self.env.now)
        self.assertEqual(event.event, self.terminal_state.name)
        self.assertEqual(event.event_type, TaskEvent.EventType.TERMINAL)
        self.assertEqual(event.status, TaskEvent.EventStatus.SUCCESS)

    def test_get(self):

        def get_value(e: Event):
            while True:
                yield self.env.timeout(5)
                t = yield self.state.get()
                e.succeed(t)

        task = Task(initial_value=50.0, complexity=1.0,
                    creation_time=0, depreciation_rate=0.1)

        self.env.run(until=1)

        self.state.put(task)

        semaphore = self.env.event()
        self.env.process(get_value(semaphore))
        self.env.run(semaphore)
        task_out: Task = semaphore.value  # type:ignore

        self.assertEqual(len(task_out.history.events), 2)
        event = task_out.history.events[1]

        self.assertEqual(event.time, 6)
        self.assertEqual(event.event, self.state.name)
        self.assertEqual(event.event_type, TaskEvent.EventType.END)
        self.assertEqual(event.status, TaskEvent.EventStatus.SUCCESS)

    def test_get_terminal(self):
        task = Task(initial_value=50.0, complexity=1.0,
                    creation_time=0, depreciation_rate=0.1)

        self.env.run(until=1)
        self.terminal_state.put(task)

        with self.assertRaises(NotImplementedError):
            _ = self.terminal_state.get()

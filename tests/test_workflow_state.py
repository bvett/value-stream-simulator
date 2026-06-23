import inspect
import unittest

from simpy import AnyOf, Environment, Event

from value_stream import EventStatus, Task, TaskEvent
from value_stream.utils import TaskFactory, TaskGenerator
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
        task = Task(initial_value=50.0, story_points=1.0, creation_time=0)

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
        self.assertEqual(event.status, EventStatus.SUCCESS)

    def test_put_terminal(self):
        task = Task(initial_value=50.0, story_points=1.0,
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
        self.assertEqual(event.status, EventStatus.SUCCESS)

    def test_get(self):

        def get_value(e: Event):
            while True:
                yield self.env.timeout(5)
                t = yield self.state.get()
                e.succeed(t)

        task = Task(initial_value=50.0, story_points=1.0,
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
        self.assertEqual(event.status, EventStatus.SUCCESS)

    def test_get_terminal(self):
        task = Task(initial_value=50.0, story_points=1.0,
                    creation_time=0, depreciation_rate=0.1)

        self.env.run(until=1)
        self.terminal_state.put(task)

        with self.assertRaises(NotImplementedError):
            _ = self.terminal_state.get()

    def test_alarm(self):

        # test for terminal and non-terminal workflow states

        env = Environment()

        targets: list[WorkflowState] = [TerminalWorkflowState(
            env, WorkflowStateName.DEPLOYMENT),
            WorkflowState(env, WorkflowStateName.DEPLOYMENT)]

        for target in targets:

            # generate 1 task per tick
            factory = TaskFactory(
                env=env, initial_value=0, story_points=1)
            generator = TaskGenerator(factory, 1)

            signal = env.event()
            limit = 10
            target.set_alarm(limit=limit, signal=signal)
            generator.start(env, target=target)

            env.run(until=signal)
            generator.stop()

            items = signal.value
            self.assertIsNotNone(items)
            self.assertTrue(isinstance(items, list))
            self.assertEqual(len(items), limit)  # type:ignore

            with self.assertRaises(ValueError):
                target.set_alarm(limit=limit * 2, signal=signal)

    def test_validation(self):
        target = TerminalWorkflowState(self.env, WorkflowStateName.DEPLOYMENT)

        with self.assertRaises(ValueError):
            signal = self.env.event()
            target.set_alarm(limit=0, signal=signal)

        with self.assertRaises(ValueError):
            signal = self.env.event()
            target.set_alarm(limit=-1, signal=signal)

    def test_restart(self):

        target = TerminalWorkflowState(self.env, WorkflowStateName.DEPLOYMENT)

        factory = TaskFactory(
            env=self.env, initial_value=0, story_points=1)
        generator = TaskGenerator(factory, 1)

        signal_1 = self.env.event()
        limit_1 = 10
        target.set_alarm(limit=limit_1, signal=signal_1)
        generator.start(self.env, target=target)

        self.env.run(until=signal_1)
        generator.stop()

        self.assertIsNotNone(signal_1.value)
        items_1 = signal_1.value
        self.assertTrue(isinstance(items_1, list))
        self.assertEqual(len(items_1), limit_1)  # type: ignore

        signal_2 = self.env.event()
        limit_2 = 5

        with self.assertRaises(ValueError):
            target.set_alarm(limit_1, signal_2)

        with self.assertRaises(ValueError):
            target.set_alarm(limit_2, signal_1)

        target.set_alarm(limit_1 + limit_2, signal_2)

        generator.start(self.env, target=target)
        self.env.run(until=signal_2)
        generator.stop()

        self.assertIsNotNone(signal_2.value)
        items_2 = signal_2.value
        self.assertTrue(isinstance(items_2, list))
        self.assertEqual(len(items_2), limit_2)  # type:ignore

        self.assertEqual(limit_1 + limit_2, len(target.items))

    def test_surpass(self):

        # try to exceed alarm limit by not yielding correctly
        def populate_without_yield(t: WorkflowState, count: int):
            for _ in range(count):
                t.put(Task(initial_value=0, story_points=0))

            t.put(Task(initial_value=0, story_points=0))

        def populate_with_yield(t: WorkflowState, count: int):
            for _ in range(count):
                yield t.put(Task(initial_value=0, story_points=0))

            yield t.put(Task(initial_value=0, story_points=0))

        for cls in [WorkflowState, TerminalWorkflowState]:
            for pop_func in [populate_without_yield, populate_with_yield]:

                env = Environment()
                target = cls(env, WorkflowStateName.DEVELOPMENT)
                signal = env.event()
                limit = 5

                target.set_alarm(limit, signal)
                timeout = env.timeout(2 * limit)

                if inspect.isgeneratorfunction(pop_func):
                    env.process(pop_func(target, limit))
                else:
                    pop_func(target, limit)

                env.run(until=AnyOf(env, [signal, timeout]))
                self.assertTrue(signal.triggered)
                self.assertEqual(len(target.items), limit)

                with self.assertRaises(ValueError):
                    target.put(Task(initial_value=0, story_points=1))

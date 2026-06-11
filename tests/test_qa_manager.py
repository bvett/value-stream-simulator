import unittest

from simpy import Environment, Store

from value_stream import DefaultSimulationPolicy, Task
from value_stream.resources import QATester, ResourceOperator


class TestQAManager(unittest.TestCase):

    def setUp(self):
        self.env = Environment()

        self.complexities = [1.0, 3.0]
        self.tasks: list[Task] = []

        for c in self.complexities:
            self.tasks.append(Task(initial_value=1.0, story_points=c))

        self.policy = DefaultSimulationPolicy()

    def _process_task(self, task: Task, m: ResourceOperator, t: Store):
        e = m.request()

        operator = yield e

        yield self.env.process(operator.operate(self.env, [task], t, policy=self.policy))
        yield m.release(operator)

    def _test_loop(self, m: ResourceOperator, t: Store):
        for task in self.tasks:
            self.env.process(self._process_task(task, m, t))

    def test_serial(self):

        # 1 QA Tester, 2 Tasks
        manager = ResourceOperator(
            self.env, QATester.create_pool(limit=1), policy=self.policy)
        target = Store(self.env)

        self._test_loop(manager, target)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, sum(self.complexities)*0.1)

    def test_parallel(self):
        # 2 QA Testers, 2 tasks

        manager = ResourceOperator(
            self.env, QATester.create_pool(limit=2), policy=self.policy)
        target = Store(self.env)

        self._test_loop(manager, target)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, max(self.complexities)*0.1)

    def test_parallel_2(self):
        # unlimited QA Testers, 2 tasks
        manager = ResourceOperator(
            self.env, QATester.create_pool(), policy=self.policy)
        target = Store(self.env)

        self._test_loop(manager, target)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, max(self.complexities)*0.1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            next(QATester.create_pool(limit=-1))

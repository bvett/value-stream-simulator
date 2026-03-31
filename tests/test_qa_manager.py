import unittest

from simpy import Environment, Store

from value_stream import Task
from value_stream.managers import QAManager
from value_stream.resources import QATester


class TestQAManager(unittest.TestCase):

    def setUp(self):
        self.env = Environment()

        self.complexities = [1.0, 3.0]
        self.tasks: list[Task] = []

        for c in self.complexities:
            self.tasks.append(Task(initial_value=1.0, complexity=c))

    def _process_task(self, task: Task, m: QAManager, t: Store):
        e = m.request()

        operator = yield e

        yield self.env.process(operator.operate(self.env, [task], t))
        yield m.release(operator)

    def _test_loop(self, m: QAManager, t: Store):
        for task in self.tasks:
            self.env.process(self._process_task(task, m, t))

    def test_serial(self):

        # 1 QA Tester, 2 Tasks
        manager = QAManager(self.env, QATester.create(limit=1))
        target = Store(self.env)

        self._test_loop(manager, target)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, sum(self.complexities)*0.1)

    def test_parallel(self):
        # 2 QA Testers, 2 tasks

        manager = QAManager(self.env, QATester.create(limit=2))
        target = Store(self.env)

        self._test_loop(manager, target)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, max(self.complexities)*0.1)

    def test_parallel_2(self):
        # unlimited QA Testers, 2 tasks
        manager = QAManager(self.env, QATester.create())
        target = Store(self.env)

        self._test_loop(manager, target)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, max(self.complexities)*0.1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            next(QATester.create(-1))

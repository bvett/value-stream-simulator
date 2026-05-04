import unittest

from simpy import Environment, Store

from value_stream import EventStatus, Task
from value_stream.utils import TaskFactory
from value_stream.resources import QATester


class TestQATester(unittest.TestCase):

    def setUp(self):

        self.tasks: list[Task] = TaskFactory().create(
            3, story_points=(x for x in range(2, 8, 2)))

        self.env = Environment()

        self.target = Store(self.env)

    def test_validation(self):
        _ = QATester()

        _ = QATester(failure_rate=0)
        _ = QATester(failure_rate=0.5)
        _ = QATester(failure_rate=1)

        with self.assertRaises(ValueError):
            _ = QATester(failure_rate=-0.01)

        with self.assertRaises(ValueError):
            _ = QATester(failure_rate=1.01)

    def test_all_successes(self):
        time_cost = 0.2
        tester = QATester(time_cost=time_cost)

        total_story_points = sum([t.story_points for t in self.tasks])

        self.env.process(tester.operate(
            self.env, self.tasks, target=self.target))

        self.env.run()

        self.assertAlmostEqual(self.env.now, time_cost * total_story_points)

        for task in self.tasks:
            self.assertEqual(task.history.last_event().status,  # type: ignore
                             EventStatus.SUCCESS)

    def test_all_failures(self):
        tester = QATester(failure_rate=1)
        self.env.process(tester.operate(
            self.env, self.tasks, target=self.target))
        self.env.run()

        for task in self.target.items:
            self.assertEqual(task.history.last_event().status,  # type: ignore
                             EventStatus.FAILURE)

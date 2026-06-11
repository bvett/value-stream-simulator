import unittest
from simpy import Environment, Store
from value_stream import DefaultSimulationPolicy, EventStatus, Task
from value_stream.resources import Toolchain
from value_stream.utils import TaskFactory


class TestToolchain(unittest.TestCase):

    def setUp(self):
        self.env = Environment()

        self.tasks: list[Task] = TaskFactory(
            initial_value=1,
            depreciation_rate=0,
            story_points=(x for x in range(2, 8, 2))).create(3)

        self.env = Environment()

        self.target = Store(self.env)

        self.policy = DefaultSimulationPolicy()

    def test_validation(self):
        _ = Toolchain(deployment_duration=100)
        _ = Toolchain(deployment_duration=0)
        _ = Toolchain(deployment_duration=1, failure_rate=0.5)
        _ = Toolchain(deployment_duration=.5, failure_rate=0)
        _ = Toolchain(deployment_duration=1, failure_rate=1)

        with self.assertRaises(ValueError):
            _ = Toolchain(deployment_duration=-0.01)
            _ = Toolchain(deployment_duration=1, failure_rate=-0.01)
            _ = Toolchain(deployment_duration=1, failure_rate=1.01)

    def test_all_successes(self):
        deployment_duration = 0.5

        toolchain = Toolchain(deployment_duration=deployment_duration)

        self.env.process(toolchain.operate(
            self.env, self.tasks, target=self.target, policy=self.policy))

        self.env.run()

        self.assertAlmostEqual(self.env.now, deployment_duration)

        for task in self.tasks:
            self.assertEqual(task.history.last_event().status,  # type: ignore
                             EventStatus.SUCCESS)

    def test_all_failures(self):

        toolchain = Toolchain(deployment_duration=1, failure_rate=1)
        self.env.process(toolchain.operate(
            self.env, self.tasks, target=self.target, policy=self.policy))
        self.env.run()

        for task in self.target.items:
            self.assertEqual(task.history.last_event().status,  # type: ignore
                             EventStatus.FAILURE)

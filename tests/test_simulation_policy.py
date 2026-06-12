import unittest

from value_stream import SimulationPolicy, DefaultSimulationPolicy, Task, SupportTask
from value_stream.assignment_strategy import AssignmentStrategy


class TestSimulationPolicy(unittest.TestCase):

    def test_simulation_policy(self):

        policy = SimulationPolicy()
        with self.assertRaises(NotImplementedError):
            policy.priority([], [])

        with self.assertRaises(NotImplementedError):
            _ = policy.support_strategy()


class TestDefaultSimulationPolicy(unittest.TestCase):

    def test_support_strategy(self):
        policy = DefaultSimulationPolicy()

        self.assertEqual(policy.support_strategy(), AssignmentStrategy.RANDOM)

    def test_priority(self):

        policy = DefaultSimulationPolicy()

        dev = Task(initial_value=1, story_points=1)
        support = SupportTask(story_points=1)

        # (t1, t2, result)

        scenarios = [
            ([], [], 0),
            ([dev], [], -1),
            ([support], [], -1),
            ([], [dev], 1),
            ([], [support], 1),
            ([dev], [dev], 0),
            ([dev], [support], 1),
            ([support], [dev], -1),
            ([support], [support], -1)
        ]

        for t1, t2, result in scenarios:
            self.assertEqual(result, policy.priority(t1, t2))

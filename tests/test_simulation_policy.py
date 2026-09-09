import unittest

from value_stream.policy import AssignmentStrategy
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.task import Task, SupportTask, TaskType


class TestDefaultSimulationPolicy(unittest.TestCase):

    def test_support_assignment_strategy(self):
        policy = DefaultSimulationPolicy()

        dev_task = Task(initial_value=1, story_points=1,
                        task_type=TaskType.DEVELOPMENT)
        support_task = Task(initial_value=1, story_points=1,
                            task_type=TaskType.SUPPORT)
        rework_task = Task(initial_value=1, story_points=1,
                           task_type=TaskType.DEVELOPMENT).as_rework()

        scenarios = [([dev_task], AssignmentStrategy.NEXT_AVAILABLE),
                     ([support_task], AssignmentStrategy.RANDOM),
                     ([rework_task], AssignmentStrategy.OWNER),
                     ([dev_task, support_task], AssignmentStrategy.NEXT_AVAILABLE),
                     ([support_task, dev_task], AssignmentStrategy.RANDOM)]

        for scenario in scenarios:
            tasks, strategy = scenario
            self.assertEqual(
                strategy, policy.support_assignment_strategy(tasks))

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
            self.assertEqual(result, policy.task_priority(t1, t2))

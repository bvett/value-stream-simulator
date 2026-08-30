import unittest

from value_stream.task import SupportTask, TaskType
from value_stream.core import WorkflowStateName

# pylint:disable=protected-access,missing-function-docstring,missing-class-docstring


class TestSupportTask(unittest.TestCase):
    def test_support_task(self):
        task = SupportTask(story_points=2,
                           task_name="INC-001",
                           creation_sim_t=2)

        self.assertEqual(task.depreciation_rate, 0)
        self.assertEqual(task.completed_story_points, 0)
        self.assertEqual(task.creation_sim_t, 2)
        self.assertEqual(task.depreciation_rate, 0.0)
        self.assertEqual(task.story_points, 2)
        self.assertEqual(task.task_name, "INC-001")
        self.assertEqual(task.task_type, TaskType.SUPPORT)
        self.assertEqual(task._initial_value, 0)

    def test_delivered_value(self):
        task = SupportTask(story_points=1)

        self.assertEqual(task._delivered_value(), 0)

        # default creation_sim_t
        task.start(2, WorkflowStateName.DELIVERY)

        # ensure value does not change until delivered
        self.assertEqual(task._delivered_value(), 0)

        # task.history.delivery_end_t = 2
        task.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task._delivered_value(), 0)

    def test_loss(self):

        # No loss
        task = SupportTask(task_name="", story_points=1,
                           creation_sim_t=0)

        task.terminate(25, WorkflowStateName.DELIVERY)

        self.assertEqual(task.loss(), 0)

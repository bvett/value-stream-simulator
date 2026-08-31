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
        self.assertEqual(task.history.completed_story_points, 0)
        self.assertEqual(task.creation_sim_t, 2)
        self.assertEqual(task.depreciation_rate, 0.0)
        self.assertEqual(task.story_points, 2)
        self.assertEqual(task.task_name, "INC-001")
        self.assertEqual(task.task_type, TaskType.SUPPORT)
        self.assertEqual(task._initial_value, 0)

    def test_delivered_value(self):
        task = SupportTask(story_points=1)

        self.assertIsNone(task.history.delivered_value)

        # default creation_sim_t
        task.start(2, WorkflowStateName.DELIVERY)

        # ensure value does not change until delivered
        self.assertIsNone(task.history.delivered_value)

        # task.history.delivery_end_t = 2
        task.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task.history.delivered_value, 0)

    def test_loss(self):

        # No loss
        task = SupportTask(task_name="", story_points=1,
                           creation_sim_t=0)

        epoch = task.history.epoch

        task.terminate(25, WorkflowStateName.DELIVERY)

        self.assertEqual(task.loss(from_epoch_t=epoch.to_epoch_time(
            task.creation_sim_t), to_epoch_t=epoch.to_epoch_time(25)), 0)

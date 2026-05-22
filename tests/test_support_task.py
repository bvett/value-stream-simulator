import unittest

from value_stream import SupportTask, TaskType, WorkflowStateName

# pylint:disable=protected-access,missing-function-docstring,missing-class-docstring


class TestSupportTask(unittest.TestCase):
    def test_support_task(self):
        task = SupportTask(story_points=2,
                           task_id="INC-001",
                           creation_time=2)

        self.assertEqual(task.depreciation_rate, 0)
        self.assertEqual(task.completed_story_points, 0)
        self.assertEqual(task.creation_t, 2)
        self.assertEqual(task.depreciation_rate, 0.0)
        self.assertEqual(task.story_points, 2)
        self.assertEqual(task.task_id, "INC-001")
        self.assertEqual(task.task_type, TaskType.SUPPORT)
        self.assertEqual(task._initial_value, 0)

    def test_delivered_value(self):
        task = SupportTask(story_points=1)

        self.assertEqual(task._delivered_value(), 0)

        # default creation_time
        task.history.start(2, WorkflowStateName.DELIVERY)

        # ensure value does not change until delivered
        self.assertEqual(task._delivered_value(), 0)

        # task.history.delivery_end_t = 2
        task.history.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task._delivered_value(), 0)

    def test_loss(self):

        # No loss
        task = SupportTask(task_id="", story_points=1,
                           creation_time=0)

        task.history.terminate(25, WorkflowStateName.DELIVERY)

        self.assertEqual(task._loss(), 0)

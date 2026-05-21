import unittest
from value_stream.task import Task, TaskType, SupportTask
from value_stream.workflow_state_name import WorkflowStateName

# pylint:disable=protected-access,missing-function-docstring,missing-class-docstring


class TestTask(unittest.TestCase):

    def test_validation(self):

        # invalid initial_value
        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=-4.2, story_points=1.0)

        # invalid story_points
        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=4.2, story_points=-1)

        # invalid depreciatiom_rate
        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=1,
                 story_points=1, depreciation_rate=-1)

        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=1,
                 story_points=1, depreciation_rate=1.1)

        # invalid creation_time

        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=100,
                 story_points=1, creation_time=-1)

        # invalid time

        with self.assertRaises(ValueError):
            task = Task(task_id="", initial_value=100,
                        story_points=1, creation_time=5)
            task.value(4)

        # edge case

        with self.assertRaises(ValueError):
            task = Task(task_id="", initial_value=100,
                        story_points=1, creation_time=5)
            task.value(0)

    def test_value(self):
        task = Task(task_id="",
                    initial_value=100,
                    story_points=1.0)

        self.assertEqual(task.value(), 100)

    def test_depreciation(self):

        # no depreciation
        task = Task(task_id="", initial_value=100,
                    story_points=1, depreciation_rate=0)

        for t in [0, 10, 200]:
            self.assertEqual(task.value(t), 100)

        # basic depreciation

        task = Task(task_id="", initial_value=100,
                    story_points=1, depreciation_rate=0.1)

        values = [100, 90, 81, 72.9]
        for i in range(0, 4):
            self.assertEqual(task.value(i), values[i])

        # depreciation with offset creation_time

        task = Task(task_id="", initial_value=100,
                    story_points=1, depreciation_rate=0.1, creation_time=5)

        values = [100, 90, 81, 72.9]
        for i, v in enumerate(range(5, 9)):
            self.assertEqual(task.value(v), values[i])

    def test_str(self):
        self.assertEqual(
            str(Task(task_id="foo", initial_value=0, story_points=1)), "foo")

    def test_loss(self):

        # No loss
        task = Task(task_id="", initial_value=50, story_points=1,
                    creation_time=0, depreciation_rate=0)

        task.history.terminate(25, WorkflowStateName.DELIVERY)

        self.assertEqual(task._loss(), 0)

        # Loss

        task = Task(task_id="", initial_value=50, story_points=1,
                    creation_time=0, depreciation_rate=0.1)

        task.history.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task._loss(), -0.19)

    def test_delivered_value(self):

        # not delivered
        task = Task(task_id="", initial_value=100,
                    story_points=1, depreciation_rate=0.1)

        self.assertEqual(task._delivered_value(), 0)

        # default creation_time
        task.history.start(2, WorkflowStateName.DELIVERY)

        # ensure value does not change until delivered
        self.assertEqual(task._delivered_value(), 0)

        # task.history.delivery_end_t = 2
        task.history.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task._delivered_value(), 81)

        # offset creation_time

        task = Task(task_id="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_time=5)

        task.history.terminate(5, WorkflowStateName.DELIVERY)

        self.assertEqual(task._delivered_value(), 100)

        task = Task(task_id="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_time=5)

        task.history.terminate(6, WorkflowStateName.DELIVERY)
        self.assertEqual(task._delivered_value(), 90)

        # validation
        task = Task(task_id="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_time=5)

        # missing delivery_start_t
        with self.assertRaises(ValueError):
            task.history.end(5, WorkflowStateName.DELIVERY)
            task._delivered_value()

        task = Task(task_id="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_time=5)

        # inverted start/end times
        with self.assertRaises(ValueError):
            task.history.start(6, WorkflowStateName.DELIVERY)
            task.history.terminate(5, WorkflowStateName.DELIVERY)
            task._delivered_value()

    def test_reset(self):

        task = Task(task_id="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_time=5)

        self.assertEqual(len(task.history.events), 0)
        task.history.start(0, WorkflowStateName.PENDING)
        task.history.end(0, WorkflowStateName.PENDING)

        self.assertEqual(len(task.history.events), 2)

        self.assertEqual(len(task.reset().history.events), 0)

    def test_completed_story_points(self):

        original_story_points = 50

        def create_task(story_points: int):
            return Task(task_id="", initial_value=100,
                        story_points=story_points)

        task = create_task(original_story_points)

        self.assertEqual(task.remaining_work(), original_story_points)

        effort = 10
        remainder = task.do_work(effort)

        self.assertEqual(task.story_points, original_story_points)
        self.assertEqual(task.completed_story_points, effort)
        self.assertEqual(task.remaining_work(), original_story_points - effort)
        self.assertEqual(remainder, 0)

        task = create_task(original_story_points)
        remainder = task.do_work(task.remaining_work())

        self.assertEqual(remainder, 0)
        self.assertEqual(task.remaining_work(), 0)

        # test regression
        task = create_task(original_story_points)
        with self.assertRaises(ValueError):
            task.do_work(-1)

        task = create_task(original_story_points)
        task.do_work(10)
        task.do_work(15)
        task.do_work(-3)

        self.assertEqual(task.completed_story_points, 22)

        remainder = task.do_work(40)
        self.assertEqual(task.remaining_work(), 0)
        self.assertEqual(remainder, 12)

        task = task.reset()
        self.assertEqual(task.remaining_work(), task.story_points)

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

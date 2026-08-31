import unittest
from value_stream.task import Task
from value_stream.core import WorkflowStateName

# pylint:disable=protected-access,missing-function-docstring,missing-class-docstring


class TestTask(unittest.TestCase):

    def test_validation(self):

        # invalid initial_value
        with self.assertRaises(ValueError):
            Task(task_name="", initial_value=-4.2, story_points=1.0)

        # invalid story_points
        with self.assertRaises(ValueError):
            Task(task_name="", initial_value=4.2, story_points=-1)

        # invalid depreciatiom_rate
        with self.assertRaises(ValueError):
            Task(task_name="", initial_value=1,
                 story_points=1, depreciation_rate=-1)

        with self.assertRaises(ValueError):
            Task(task_name="", initial_value=1,
                 story_points=1, depreciation_rate=1.1)

        # invalid creation_time

        with self.assertRaises(ValueError):
            Task(task_name="", initial_value=100,
                 story_points=1, creation_sim_t=-1)

    def test_value(self):
        task = Task(task_name="",
                    initial_value=100,
                    story_points=1.0)

        self.assertEqual(task.value(), 100)

    def test_depreciation(self):

        # no depreciation
        task = Task(task_name="", initial_value=100,
                    story_points=1, depreciation_rate=0)

        for t in [0, 10, 200]:
            self.assertEqual(task.value(t), 100)

        # basic depreciation

        task = Task(task_name="", initial_value=100,
                    story_points=1, depreciation_rate=0.1)

        values = [100, 90, 81, 72.9]
        for i, v in enumerate(values):
            self.assertEqual(task.value(i), v)

        # depreciation with offset creation_time

        task = Task(task_name="", initial_value=100,
                    story_points=1, depreciation_rate=0.1, creation_sim_t=5)

        values = [100, 90, 81, 72.9]
        for i, v in enumerate(values):
            self.assertEqual(task.value(i), v)

    def test_str(self):
        self.assertEqual(
            str(Task(task_name="foo", initial_value=0, story_points=1)), "foo")

    def test_loss(self):

        # No loss
        task = Task(task_name="", initial_value=50, story_points=1,
                    creation_sim_t=0, depreciation_rate=0)

        task.terminate(25, WorkflowStateName.DELIVERY)

        epoch = task.history.epoch

        self.assertEqual(task.loss(from_epoch_t=epoch.to_epoch_time(
            task.creation_sim_t), to_epoch_t=epoch.to_epoch_time(25)), 0)

        # Loss

        task = Task(task_name="", initial_value=50, story_points=1,
                    creation_sim_t=0, depreciation_rate=0.1)

        epoch = task.history.epoch

        task.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task.loss(from_epoch_t=epoch.to_epoch_time(
            task.creation_sim_t), to_epoch_t=epoch.to_epoch_time(2)), -0.19)

    def test_delivered_value(self):

        # not delivered
        task = Task(task_name="", initial_value=100,
                    story_points=1, depreciation_rate=0.1)

        self.assertIsNone(task.history.delivered_value)

        # default creation_time
        task.start(2, WorkflowStateName.DELIVERY)

        # ensure value does not change until delivered
        self.assertIsNone(task.history.delivered_value)

        # task.history.delivery_end_t = 2
        task.terminate(2, WorkflowStateName.DELIVERY)

        self.assertEqual(task.history.delivered_value, 81)

        # offset creation_time

        task = Task(task_name="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_sim_t=5)

        task.terminate(5, WorkflowStateName.DELIVERY)

        self.assertEqual(task.history.delivered_value, 100)

        task = Task(task_name="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_sim_t=5)

        task.terminate(6, WorkflowStateName.DELIVERY)
        self.assertEqual(task.history.delivered_value, 90)

        # validation
        task = Task(task_name="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_sim_t=5)

        # missing delivery_start_t
        with self.assertRaises(ValueError):
            task.end(5, WorkflowStateName.DELIVERY)

        task = Task(task_name="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_sim_t=5)

        # inverted start/end times
        with self.assertRaises(ValueError):
            task.start(6, WorkflowStateName.DELIVERY)
            task.terminate(5, WorkflowStateName.DELIVERY)

    def test_reset(self):

        task = Task(task_name="", initial_value=100, story_points=1,
                    depreciation_rate=0.1, creation_sim_t=5)

        self.assertEqual(len(task.history.events), 0)
        task.start(5, WorkflowStateName.PENDING)
        task.end(5, WorkflowStateName.PENDING)

        self.assertEqual(len(task.history.events), 2)

        new_task = task.reset()
        self.assertEqual(len(new_task.history.events), 0)
        self.assertNotEqual(task.task_id, new_task.task_id)

    def test_completed_story_points(self):

        original_story_points = 50

        def create_task(story_points: int):
            return Task(task_name="", initial_value=100,
                        story_points=story_points)

        task = create_task(original_story_points)

        self.assertEqual(task.remaining_work(), original_story_points)

        effort = 10
        remainder = task.do_work(effort)

        self.assertEqual(task.story_points, original_story_points)
        self.assertEqual(task.history.completed_story_points, effort)
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

        self.assertEqual(task.history.completed_story_points, 22)

        remainder = task.do_work(40)
        self.assertEqual(task.remaining_work(), 0)
        self.assertEqual(remainder, 12)

        task = task.reset()
        self.assertEqual(task.remaining_work(), task.story_points)

    def test_value_2(self):
        # test calculation of depreciated values of a collection of tasks.
        # test total incremental loss that occurs from a collection of tasks between times t1 and t2
        # what happens when the collection changes between t1 and t2?
        # take a snapshot of the collection, then follow the tasks to make it independent of collection?
        # some tasks may leave at t1.5 - their loss is fixed from that point forward.
        # between t1 and t2 *and* has not left the collection
        # between t1 and min (t2, leaving collection)

        # what if it was added after t1?

        # between (max(t1, t-added) and min(t2, t-removed))

        # hey dummy.  task_history is the authoratative take on a task's progress through a workflow.
        # use that
        # still need a way to capture incremental loss for a task between 2 times, relative to initial value.

        pass

    def test_task_id(self):
        task_1 = Task(task_name="", initial_value=100, story_points=1,
                      depreciation_rate=0.1, creation_sim_t=5)

        self.assertIsNotNone(task_1.task_id)

        task_2 = Task(task_name="", initial_value=100, story_points=1,
                      depreciation_rate=0.1, creation_sim_t=5)

        self.assertNotEqual(task_1.task_id, task_2.task_id)

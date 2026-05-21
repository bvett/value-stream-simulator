import unittest
from simpy import Environment
from value_stream.workflow_state_name import WorkflowStateName
from value_stream.resources import Developer
from value_stream.task import Task
from value_stream.workflow_state import WorkflowState

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloper(unittest.TestCase):

    def setUp(self):

        self.simple_task = Task(task_id="", initial_value=1, story_points=.6)
        self.complex_task = Task(task_id="", initial_value=1, story_points=2)

    def test_validation(self):

        with self.assertRaises(ValueError):
            Developer(0)

        with self.assertRaises(ValueError):
            Developer(-1)

    def test_developer(self):

        junior_developer = Developer(.5, name="junior")
        senior_developer = Developer(1.5, name="senior")

        env = Environment()
        target = WorkflowState(env, WorkflowStateName.DEVELOPMENT)

        for dev in [junior_developer, senior_developer]:
            for task in [self.simple_task.reset(), self.complex_task.reset()]:
                self.assertEqual(task.remaining_work(), task.story_points)
                env.process(dev.operate(env, [task], target))

        env.run()

        # All tasks are started at t=0
        # Each developer is assigned simple_task then complex_task
        # Processing of simple_task is suspended until complex_task is completed.

        # Expected completion times (start_time + effort)

        # (senior_dev, complex_task) : 0 + (2/1.5) = 1.3333333
        # (senior_dev, simple_task)  : 1.3333333 + (0.6/1.5) = 1.7333333
        # (junior_dev, complex_task) : 0 + (2/0.5) = 4
        # (junior_dev, simple_task)  : 4 + (0.6/0.5) = 5.2

        for i, v in enumerate([1.3333333, 1.7333333, 4, 5.2]):

            dev_start_t, dev_end_t = target.items[i].history.event_times(
                WorkflowStateName.DEVELOPMENT)
            self.assertAlmostEqual(dev_end_t, v)
            self.assertEqual(dev_start_t, 0)

            self.assertAlmostEqual(target.items[i].remaining_work(), 0)

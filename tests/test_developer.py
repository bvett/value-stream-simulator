import unittest
from simpy import Environment
from value_stream.workflow_state_name import WorkflowStateName
from value_stream.resources import Developer
from value_stream.task import Task
from value_stream.workflow_state import WorkflowState

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloper(unittest.TestCase):

    def setUp(self):

        self.simple_task = Task(task_id="", initial_value=1, complexity=.6)
        self.complex_task = Task(task_id="", initial_value=1, complexity=2)

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
                env.process(dev.operate(env, [task], target))

        env.run()

        for i, v in enumerate([0.4, 1.2, 1.3333333, 4]):

            dev_start_t, dev_end_t = target.items[i].history.event_times(
                WorkflowStateName.DEVELOPMENT)
            self.assertAlmostEqual(dev_end_t, v)
            self.assertEqual(dev_start_t, 0)

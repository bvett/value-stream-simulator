import unittest
from simpy import Environment
from value_stream.workflow_state_name import WorkflowStateName
from value_stream.resources import Developer, ResourceOperator
from value_stream.task import SupportTask, Task
from value_stream.utils import TaskFactory, TaskGenerator
from value_stream.workflow_state import TerminalWorkflowState, WorkflowState
from value_stream.support_workflow import SupportWorkflow

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

    def test_interruption(self):
        """validates that the total development time of a task is increased by the time required to 
        complete a support task that is assigned to the developer"""

        def run_scenario(env: Environment, support_generator: TaskGenerator | None, support_target: WorkflowState | None):

            dev_efficiency = 1
            story_points = 2
            developer = Developer(efficiency=1, name="D1")
            dev_task = Task(initial_value=1, story_points=2, task_id="T1")
            dev_target = TerminalWorkflowState(
                env=env, name=WorkflowStateName.DEV_COMPLETE)

            operator = ResourceOperator(env=env, resources=[developer])

            dev_source = WorkflowState(
                env=env, name=WorkflowStateName.PENDING)
            dev_source.put(dev_task)

            operator.start(dev_source, dev_target)

            if (support_generator is not None) and (support_target is not None):

                support_workflow = SupportWorkflow(env, support_target)

                env.process(support_workflow.start(
                    support_generator, developers=[developer]))

                sim_duration = ((story_points + 1) / dev_efficiency) + 5

            else:
                sim_duration = (story_points / dev_efficiency) + 1

            env.run(until=sim_duration)

            return dev_target

        env = Environment()
        dev_target = run_scenario(env, None, None)

        self.assertEqual(1, len(dev_target.items))
        task: Task = dev_target.items[-1]

        self.assertEqual((2.0, 2.0), task.history.event_times(
            WorkflowStateName.DEV_COMPLETE))

        # assert the events in dev_target

        env = Environment()
        support_task_factory = TaskFactory(SupportTask, story_points=1)

        support_target = WorkflowState(
            env=env, name=WorkflowStateName.SUPPORT_COMPLETE)

        support_generator = TaskGenerator(
            factory=support_task_factory, interval=1.5)

        dev_target = run_scenario(env, support_generator, support_target)
        task = dev_target.items[-1]

        self.assertEqual(1, len(dev_target.items))
        self.assertEqual((3.0, 3.0), task.history.event_times(
            WorkflowStateName.DEV_COMPLETE))

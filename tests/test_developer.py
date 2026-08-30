import unittest
from simpy import Environment
from value_stream.core import WorkflowStateName
from value_stream.resources import Developer, ResourceTracker
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.task import SupportTask, Task, TaskFactory, TaskGenerator
from value_stream.workflow import ResourceOperator, SupportWorkflow, TerminalWorkflowState, WorkflowState

from .testutils import TestUtils

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloper(unittest.TestCase, TestUtils):

    def setUp(self):

        self.simple_task = Task(task_name="", initial_value=1, story_points=.6)
        self.complex_task = Task(task_name="", initial_value=1, story_points=2)
        self.policy = DefaultSimulationPolicy()
        self.env = Environment()
        self.tracker = ResourceTracker(self.env)

    def test_validation(self):

        with self.assertRaises(ValueError):
            Developer(0)

        with self.assertRaises(ValueError):
            Developer(-1)

    def test_developer(self):

        junior_developer = Developer(.5, name="junior")
        senior_developer = Developer(1.5, name="senior")

        target = WorkflowState(self.env, WorkflowStateName.DEVELOPMENT)

        for dev in [junior_developer, senior_developer]:
            for task in [self.simple_task.reset(), self.complex_task.reset()]:
                self.assertEqual(task.remaining_work(), task.story_points)
                self.env.process(dev.operate(
                    self.env, [task], target, policy=self.policy, tracker=self.tracker))

        self.env.run()

        # All tasks are started at t=0
        # Each developer is assigned simple_task then complex_task
        # Processing of complex_task is suspended until simple_task is completed.
        #   - due to DefaultSimulationPolicy - development tasks must
        #       wait for existing devevlopment tasks to complete

        # Expected completion times (start_time + effort)

        # (senior_dev, simple_task)  : 0 + (0.6/1.5) = 0.4
        # (senior_dev, complex_task) : 0.4 + (2/1.5) = 1.7333333
        # (junior_dev, simple_task)  : 0 + (0.6/0.5) = 1.2
        # (junior_dev, complex_task) : 1.2 + (2/0.5) = 5.2

        for i, v in enumerate([0.4, 1.2, 1.7333333, 5.2]):

            dev_start_t, dev_end_t = self.event_times(
                target.items[i].history, WorkflowStateName.DEVELOPMENT)
            self.assertAlmostEqual(dev_end_t, v)
            self.assertEqual(dev_start_t, 0)

            self.assertAlmostEqual(target.items[i].remaining_work(), 0)

    def test_interruption(self):
        """validates that the total development time of a task is increased by the time required to
        complete a support task that is assigned to the developer"""

        def run_scenario(env: Environment,
                         dev_efficiency: float,
                         story_points: float,
                         support_generator: TaskGenerator | None,
                         support_target: WorkflowState | None,
                         interval: float | None = None):

            developer = Developer(efficiency=1, name="D1")

            dev_source = WorkflowState(
                env=env, name=WorkflowStateName.PENDING)

            num_tasks = 2
            for i in range(0, num_tasks):

                dev_task = Task(initial_value=1,
                                story_points=story_points, task_name=f"T{i+1}")
                dev_source.put(dev_task)

            dev_target = TerminalWorkflowState(
                env=env, name=WorkflowStateName.DEV_COMPLETE)

            operator = ResourceOperator(
                env=env, resources=[developer], policy=self.policy, tracker=self.tracker)

            operator.start(dev_source, dev_target)

            if (support_generator is not None) and (support_target is not None) and (interval is not None):

                support_workflow = SupportWorkflow(
                    env, resource_policy=self.policy, workflow_policy=self.policy)

                env.process(support_workflow.start(
                    generator=support_generator,
                    developers=[developer],
                    interval=interval, tracker=self.tracker))

                sim_duration = (
                    (num_tasks * story_points + 1) / dev_efficiency) + 5

            else:
                sim_duration = (num_tasks * story_points / dev_efficiency) + 1
            print(f"sim_duration:{sim_duration}")
            env.run(until=sim_duration)

            return dev_target

        # Scenario 1: No support burden
        env = Environment()
        dev_target = run_scenario(
            env,
            dev_efficiency=1,
            story_points=2,
            support_generator=None,
            support_target=None)

        self.assertEqual(2, len(dev_target.items))

        self.assertEqual((2.0, 2.0), self.event_times(
            dev_target.items[0].history, WorkflowStateName.DEV_COMPLETE))

        # Scenario 2: Support that arrives mid-task (non-aligned interval)
        env = Environment()
        support_task_factory = TaskFactory(SupportTask, story_points=1)

        support_target = WorkflowState(
            env=env, name=WorkflowStateName.SUPPORT_COMPLETE)

        support_generator = TaskGenerator(
            factory=support_task_factory)

        dev_target = run_scenario(env,
                                  dev_efficiency=1,
                                  story_points=2,
                                  support_generator=support_generator,
                                  support_target=support_target,
                                  interval=1.5)

        self.assertEqual(2, len(dev_target.items))
        self.assertEqual((3.0, 3.0), self.event_times(
            dev_target.items[0].history, WorkflowStateName.DEV_COMPLETE))

        # Scenario 3: Support that arrives as development task ends/begins
        env = Environment()

        support_target = WorkflowState(
            env=env, name=WorkflowStateName.SUPPORT_COMPLETE)

        support_generator = TaskGenerator(
            factory=support_task_factory, limit=1)

        dev_target = run_scenario(env,
                                  dev_efficiency=1,
                                  story_points=2,
                                  support_generator=support_generator,
                                  support_target=support_target,
                                  interval=2)

        self.assertEqual(2, len(dev_target.items))
        self.assertEqual((2.0, 2.0), self.event_times(
            dev_target.items[0].history, WorkflowStateName.DEV_COMPLETE))

        # Second task should have been delayed by support
        self.assertEqual((5.0, 5.0), self.event_times(
            dev_target.items[-1].history, WorkflowStateName.DEV_COMPLETE))

import unittest
from pydantic import ValidationError
from simpy import Environment
from value_stream.workflow import SDLCWorkflow
from value_stream.resources import Developer, ResourceTracker
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.factory import TaskFactory
from value_stream.task import SupportTask, Task, DefaultRouter, TypeRouter
from value_stream.workflow import ResourceOperator, SupportWorkflow, TerminalTaskStore, TaskStore

from ..testutils import TestUtils

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloper(unittest.TestCase, TestUtils):

    def setUp(self):

        self.simple_task = Task(
            task_name="simple", initial_value=1, story_points=.6)
        self.complex_task = Task(
            task_name="complex", initial_value=1, story_points=2)
        self.policy = DefaultSimulationPolicy()
        self.env = Environment()
        self.tracker = ResourceTracker(self.env)

    def test_validation(self):

        with self.assertRaises(ValidationError):
            Developer(efficiency=0)

        with self.assertRaises(ValidationError):
            Developer(efficiency=-1)

    def test_developer(self):

        junior_developer = Developer(efficiency=.5, name="junior")
        senior_developer = Developer(efficiency=1.5, name="senior")

        workflow_state = SDLCWorkflow.WorkflowState.DEVELOPMENT
        target = TaskStore(self.env, SDLCWorkflow.WorkflowState.DEVELOPMENT)

        task_router = DefaultRouter(target)

        for dev in [junior_developer, senior_developer]:
            for task in [self.simple_task.reset(), self.complex_task.reset()]:
                self.assertEqual(task.remaining_work(), task.story_points)
                self.env.process(dev.operate(
                    self.env, [task], task_router=task_router, workflow_state=workflow_state, policy=self.policy, tracker=self.tracker))

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
                target.items[i].history, SDLCWorkflow.WorkflowState.DEVELOPMENT)
            self.assertAlmostEqual(dev_end_t, v)
            self.assertEqual(dev_start_t, 0)

            self.assertAlmostEqual(target.items[i].remaining_work(), 0)

    def test_interruption(self):
        """validates that the total development time of a task is increased by the time required to
        complete a support task that is assigned to the developer"""

        def run_scenario(env: Environment,
                         dev_efficiency: float,
                         story_points: float,
                         support_target: TaskStore | None,
                         generate_support: bool = False,
                         interval: float | None = None,
                         limit: int | None = None):

            developer = Developer(efficiency=1, name="D1")

            dev_source = TaskStore(
                env=env, name=SDLCWorkflow.WorkflowState.PENDING)

            num_tasks = 2
            for i in range(0, num_tasks):

                dev_task = Task(initial_value=1,
                                story_points=story_points, task_name=f"T{i+1}")
                dev_source.put(dev_task)

            dev_target = TerminalTaskStore(
                env=env, name=SDLCWorkflow.WorkflowState.DEV_COMPLETE)

            if support_target is not None:
                task_router = TypeRouter(
                    on_development=dev_target, on_support=support_target)
            else:
                task_router = DefaultRouter(dev_target)

            operator = ResourceOperator(
                env=env, resources=[developer], workflow_policy=self.policy, resource_policy=self.policy, tracker=self.tracker)

            operator.start(
                dev_source, SDLCWorkflow.WorkflowState.DEVELOPMENT, task_router=task_router)

            if generate_support is True and interval is not None:

                support_workflow = SupportWorkflow(story_points=1, limit=limit)

                support_workflow.start(env=env, interval=interval,
                                       target=dev_source)

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
            generate_support=False,
            support_target=None)

        self.assertEqual(2, len(dev_target.items))

        self.assertEqual((2.0, 2.0), self.event_times(
            dev_target.items[0].history, SDLCWorkflow.WorkflowState.DEV_COMPLETE))

        # Scenario 2: Support that arrives mid-task (non-aligned interval)
        env = Environment()

        support_target = TaskStore(
            env=env, name=SDLCWorkflow.WorkflowState.SUPPORT_COMPLETE)

        dev_target = run_scenario(env,
                                  dev_efficiency=1,
                                  story_points=2,
                                  generate_support=True,
                                  support_target=support_target,
                                  interval=1.5)

        self.assertEqual(2, len(dev_target.items))
        self.assertEqual((3.0, 3.0), self.event_times(
            dev_target.items[0].history, SDLCWorkflow.WorkflowState.DEV_COMPLETE))

        # Scenario 3: Support that arrives as development task ends/begins
        env = Environment()

        support_target = TaskStore(
            env=env, name=SDLCWorkflow.WorkflowState.SUPPORT_COMPLETE)

        dev_target = run_scenario(env,
                                  dev_efficiency=1,
                                  story_points=2,
                                  generate_support=True,
                                  support_target=support_target,
                                  interval=2,
                                  limit=1)

        self.assertEqual(2, len(dev_target.items))
        self.assertEqual((2.0, 2.0), self.event_times(
            dev_target.items[0].history, SDLCWorkflow.WorkflowState.DEV_COMPLETE))

        # Second task should have been delayed by support
        self.assertEqual((5.0, 5.0), self.event_times(
            dev_target.items[-1].history, SDLCWorkflow.WorkflowState.DEV_COMPLETE))

    def test_deferral(self):
        """test that the arrival of a second, non-interrupting workload is queued until the first completes"""

        developer = Developer()

        workflow_state = SDLCWorkflow.WorkflowState.DEVELOPMENT
        target = TaskStore(self.env, SDLCWorkflow.WorkflowState.DEVELOPMENT)

        task_router = DefaultRouter(target)

        self.env.process(developer.operate(
            self.env, [self.complex_task],
            task_router=task_router,
            workflow_state=workflow_state,
            policy=self.policy,
            tracker=self.tracker))

        self.env.run(1)

        self.env.process(developer.operate(
            self.env, [self.simple_task],
            task_router=task_router,
            workflow_state=workflow_state,
            policy=self.policy,
            tracker=self.tracker))

        self.env.run()
        self.assertEqual(2, len(target.items))
        self.assertEqual(self.complex_task.story_points +
                         self.simple_task.story_points, self.env.now)

        self.assertEqual(target.items[0].task_name, 'complex')
        self.assertEqual(target.items[1].task_name, 'simple')

    def test_multi_deferral(self):
        """when presented with a series of support tasks, validate that they are handled in LIFO order"""

        developer = Developer(efficiency=1)

        workflow_state = SDLCWorkflow.WorkflowState.DEVELOPMENT
        target = TaskStore(self.env, SDLCWorkflow.WorkflowState.DEVELOPMENT)

        task_router = DefaultRouter(target)

        support_task_factory = TaskFactory(SupportTask, story_points=1)

        # create support tasks faster than the developer can process.
        # this should result in the developer being constantly interrupted
        # and processing the tasks in LIFO order

        def produce_support(env: Environment, iterations: int, interval: float = 0.5):
            support_tasks = support_task_factory.create(
                count=iterations, env=env, shuffle=False)

            for support_task in support_tasks:

                print(f"t={env.now} sending {support_task.task_name}")
                env.process(developer.operate(env=env,
                                              tasks=[support_task],
                                              task_router=task_router,
                                              policy=self.policy, workflow_state=workflow_state,
                                              tracker=self.tracker))

                yield env.timeout(interval)

        self.env.process(produce_support(
            env=self.env, iterations=10, interval=0.5))

        self.env.run()

        self.assertEqual(10, len(target.items))

        self.assertEqual('10', target.items[0].task_name)
        self.assertEqual('1', target.items[-1].task_name)

    def test_do_no_work(self):
        """tests an edge case of a task with zero story points"""
        workflow_state = SDLCWorkflow.WorkflowState.DEVELOPMENT
        target = TaskStore(self.env, SDLCWorkflow.WorkflowState.DEVELOPMENT)

        task_router = DefaultRouter(target)

        developer = Developer(efficiency=1)

        easy_task = Task(initial_value=0, story_points=0)

        self.env.process(developer.operate(
            self.env, [easy_task], task_router=task_router,
            workflow_state=workflow_state, policy=self.policy, tracker=self.tracker))

        self.env.run()

        self.assertEqual(0, self.env.now)
        self.assertEqual(1, len(target.items))

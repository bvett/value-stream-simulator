import math
import numpy as np
import random
import unittest

from simpy import Environment
from value_stream import DefaultSimulationPolicy
from value_stream.assignment_strategy import AssignmentStrategy
from value_stream.support_workflow import SupportWorkflow
from value_stream import SupportTask, Task, WorkflowState, WorkflowStateName
from value_stream.resources import Developer
from value_stream.utils import DeveloperFactory, TaskFactory, TaskGenerator


# pylint:disable=missing-class-docstring,missing-function-docstring


class TestSupportWorkflow(unittest.TestCase):
    # pylint: disable=W0212
    def setUp(self):
        random.seed(42)
        self.policy = DefaultSimulationPolicy()

    def execute_scenario(self,
                         sim_duration: float,
                         support_interval: float,
                         story_points: float,
                         developer_efficiency: float,
                         developer_count: int):
        """ helper function that executes a scenario and returns the number of tasks processed"""

        env = Environment()

        workflow = SupportWorkflow(env, policy=self.policy)

        developers = DeveloperFactory().create(
            count=developer_count,
            efficiency=developer_efficiency)

        task_factory = TaskFactory(cls=SupportTask,
                                   story_points=story_points)

        task_generator = TaskGenerator(
            factory=task_factory,
            interval=support_interval)

        env.process(workflow.start(
            generator=task_generator, developers=developers))

        signal = env.timeout(sim_duration)

        env.run(until=signal)

        num_queued_items = 0
        num_abandoned_items = 0
        for developer in developers:
            num_queued_items += len(developer._suspended_work)
            if developer._process is not None:
                num_abandoned_items += 1

        completed = workflow.completed
        if completed is None:
            raise ValueError("completed is None")
        return len(completed), num_queued_items, num_abandoned_items

    def test_interruptions(self):
        """test ability of a team of busy developers to complete support tasks"""

        # scenarios that simulate workloads ranging from light to overload

        scenarios = []

        sim_duration = 100

        for developer_efficiency in np.arange(0.5, 2.5, 0.5):
            for support_interval in [0.25, 0.5, 1.0, 2.0]:
                for story_points in range(1, 4):
                    for developer_count in range(1, 5):
                        scenarios.append({
                            'developer_efficiency': developer_efficiency,
                            'support_interval': support_interval,
                            'story_points': story_points,
                            'sim_duration': sim_duration,
                            'developer_count': developer_count
                        })

        for s in scenarios:

            # validate that all tasks are accounted for when the simulation ends
            #  delivered_tasks: completed tasks
            #  queued_tasks: partially-completed tasks that result from interruptions
            #  abandoned_tasks: tasks that the developers were working on when the simulation was terminated
            try:

                delivered_tasks, queued_tasks, abandoned_tasks = self.execute_scenario(
                    **s)

                total_generated_tasks = math.floor((s['sim_duration'] - s['support_interval']) /
                                                   (s['support_interval']))

                print(
                    f"validating {delivered_tasks}+{queued_tasks}+{abandoned_tasks}={total_generated_tasks} for scenario {s}")
                self.assertEqual(total_generated_tasks,
                                 delivered_tasks + queued_tasks + abandoned_tasks,
                                 msg=f"{delivered_tasks} + {queued_tasks} + {abandoned_tasks} != {total_generated_tasks}")

            except Exception:
                print(f"exception processing scenario: {s}")
                raise

    def test_queuing(self):
        """test ability of a single developer to complete support tasks in LIFO order"""

        developer_efficiency = 1
        developer = Developer(efficiency=developer_efficiency)
        env = Environment()

        source = WorkflowState(env,
                               WorkflowStateName.SUPPORT_PENDING)
        target = WorkflowState(
            env, WorkflowStateName.SUPPORT_COMPLETE)

        workflow = SupportWorkflow(env, policy=self.policy)

        story_points = 5
        for i in range(1, 4):
            source.put(SupportTask(
                story_points=story_points, task_id=f"T{i}"))

        env.process(workflow._processing_loop(
            [developer],
            strategy=AssignmentStrategy.RANDOM,
            source=source,
            target=target
        ))

        env.run(until=1)

        # Check that the developer has queued up all 3 tasks
        self.assertEqual(len(developer._suspended_work), 2)

        env.run(until=(1 * story_points) + 1)

        # Check that T3 has been completed and the developer has 1 task queued up
        self.assertEqual(len(target.items), 1)
        self.assertEqual(target.items[-1].task_id, "T3")
        self.assertEqual(len(developer._suspended_work), 1)

        env.run(until=(3 * story_points) + 1)

        self.assertEqual(len(target.items), 3)
        self.assertEqual(target.items[-1].task_id, "T1")
        self.assertEqual(len(developer._suspended_work), 0)

    def test_termination(self):
        """ensure SupportWorkflow stops cleanly, including its internal task generator"""

        env = Environment()

        workflow = SupportWorkflow(env, policy=self.policy)

        developers = [Developer(efficiency=2)]

        task_factory = TaskFactory(cls=SupportTask,
                                   story_points=1)

        task_generator = TaskGenerator(
            factory=task_factory,
            interval=1)

        env.process(workflow.start(
            generator=task_generator, developers=developers))

        env.run(until=10)

        source = workflow.pending
        target = workflow.completed

        self.assertIsNotNone(source)
        self.assertIsNotNone(target)

        # Validate that set of tasks were created and processed
        self.assertEqual(9, len(target))  # type: ignore

        # Validate that no support tasks have entered the workflow
        self.assertEqual(0, len(source))  # type: ignore

        # stop the workflow
        workflow.stop()

        # advance the simulation, and assert no new tasks have been generated

        env.run(until=20)

        self.assertEqual(0, len(source))  # type: ignore
        self.assertEqual(9, len(target))  # type: ignore

    def test_validation(self):
        env = Environment()

        workflow = SupportWorkflow(env, policy=self.policy)

        developers = []

        task_factory = TaskFactory(cls=SupportTask,
                                   story_points=1)

        task_generator = TaskGenerator(
            factory=task_factory,
            interval=1)

        with self.assertRaises(ValueError):
            next(workflow.start(
                generator=task_generator, developers=developers))

    def test_assignment_strategies(self):

        class DeveloperMock(Developer):
            def __init__(self, assignment_map, **kwargs):
                super().__init__(**kwargs)
                self.assignment_map = assignment_map

            def do_work(self, env: Environment, tasks: list[Task]):
                if self.name not in self.assignment_map:
                    self.assignment_map[self.name] = 1
                else:
                    self.assignment_map[self.name] += 1

                return super().do_work(env, tasks)

        def run_scenario(num_developers, developer_efficiency, interval, iterations, strategy: AssignmentStrategy):

            class MockPolicy(DefaultSimulationPolicy):
                def __init__(self, strategy: AssignmentStrategy):
                    super().__init__()
                    self.strategy = strategy

                def support_strategy(self):
                    return self.strategy

            env = Environment()

            workflow = SupportWorkflow(
                env, policy=MockPolicy(strategy))

            task_factory = TaskFactory(cls=SupportTask,
                                       story_points=1)

            task_generator = TaskGenerator(
                factory=task_factory,
                interval=interval)

            developers = []
            assignment_map = {}
            for i in range(0, num_developers):
                developers.append(DeveloperMock(
                    assignment_map=assignment_map, efficiency=developer_efficiency, name=f"D{i}"))

            env.process(workflow.start(
                generator=task_generator, developers=developers))

            env.run(until=iterations + 1)

            return assignment_map

        num_developers = 5
        developer_efficiency = 1
        interval = 1
        iterations = 50
        assignment_map = run_scenario(num_developers=num_developers,
                                      developer_efficiency=developer_efficiency,
                                      interval=interval,
                                      iterations=iterations,
                                      strategy=AssignmentStrategy.CYCLIC)

        print(assignment_map)
        for v in assignment_map.values():
            self.assertEqual(v, (iterations / interval) / num_developers)

        assignment_map = run_scenario(num_developers=num_developers,
                                      developer_efficiency=developer_efficiency,
                                      interval=interval,
                                      iterations=iterations,
                                      strategy=AssignmentStrategy.RANDOM)

        print(assignment_map)
        total = 0
        for v in assignment_map.values():
            total += v

        self.assertEqual(total, math.floor(iterations/interval))

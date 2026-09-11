import unittest

from simpy import Environment

from value_stream.core import WorkflowStateName
from value_stream.resources import ResourceTracker
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.factories import DeveloperFactory, TaskFactory
from value_stream.task import DefaultRouter, Task
from value_stream.workflow import ResourceOperator, TaskStore


class TestResourceOperator(unittest.TestCase):
    def setUp(self):
        self.env = Environment()
        self.tracker = ResourceTracker(self.env)

        self.resources = DeveloperFactory.create(3)
        self.workflow_state = WorkflowStateName.DEVELOPMENT

        self.source = TaskStore(self.env, WorkflowStateName.PENDING)
        self.target = TaskStore(self.env, WorkflowStateName.DELIVERY)
        self.task_router = DefaultRouter(self.target)

        self.policy = DefaultSimulationPolicy()

    def test_validation(self):

        # catch negative cadence
        with self.assertRaises(ValueError):
            _ = ResourceOperator(env=self.env,
                                 resources=self.resources,
                                 cadence=-1,
                                 workflow_policy=self.policy,
                                 resource_policy=self.policy,
                                 tracker=self.tracker)

        # attempt to start twice in succession
        with self.assertRaises(RuntimeError):
            manager = ResourceOperator(env=self.env,
                                       resources=self.resources,
                                       workflow_policy=self.policy,
                                       resource_policy=self.policy,
                                       tracker=self.tracker)

            for _ in range(2):
                manager.start(source=self.source,
                              workflow_state=self.workflow_state,
                              task_router=self.task_router)

        # attempt to start after stopping
        with self.assertRaises(RuntimeError):
            manager = ResourceOperator(env=self.env,
                                       resources=self.resources,
                                       workflow_policy=self.policy,
                                       resource_policy=self.policy,
                                       tracker=self.tracker)
            for _ in range(2):
                manager.start(source=self.source,
                              workflow_state=self.workflow_state,
                              task_router=self.task_router)

                manager.stop()

        # attempt to stop a manager that has not been started
        with self.assertRaises(RuntimeError):
            manager = ResourceOperator(env=self.env,
                                       resources=self.resources,
                                       workflow_policy=self.policy,
                                       resource_policy=self.policy,
                                       tracker=self.tracker)

            manager.stop()

    # Why does this cause is_alive to remain false?

    def test_rework(self):

        num_tasks = 100

        operator = ResourceOperator(env=self.env,
                                    resources=self.resources,
                                    workflow_policy=self.policy,
                                    resource_policy=self.policy,
                                    tracker=self.tracker)

        operator.start(source=self.source, workflow_state=self.workflow_state,
                       task_router=self.task_router)

        tasks = TaskFactory(initial_value=1, story_points=1).create(
            count=num_tasks, env=self.env)

        for task in tasks:
            self.source.put(task)

        self.env.run(until=5)

        self.assertEqual(12, len(self.target.items))

        self.env.run(until=6)

        def process_rework():
            rework_task: Task = yield self.target.get()
            # rework_task.do_work(story_points=-0.25)
            print(
                f"rework_task: {rework_task.task_name}  {rework_task.remaining_work()}")
            yield self.source.put(rework_task.as_rework())

        self.env.process(process_rework())

        self.env.run()

        self.assertEqual(num_tasks, len(self.target.items))

        total_rework = 1

        for task in self.target.items:
            if task.is_rework is True:
                total_rework += 1

        self.assertEqual(1, total_rework)

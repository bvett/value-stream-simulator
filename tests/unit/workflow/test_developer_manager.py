import unittest
from simpy import Environment, Store
from value_stream.workflow import SDLCWorkflow
from value_stream.resources import Developer, ResourceTracker
from value_stream.task import Task, DefaultRouter
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.workflow import ResourceOperator, TaskStore


# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloperManager(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.tracker = ResourceTracker(self.env)
        self.source = TaskStore(self.env, SDLCWorkflow.WorkflowState.PENDING)
        self.workflow_state = SDLCWorkflow.WorkflowState.DEVELOPMENT
        self.target = TaskStore(
            self.env, SDLCWorkflow.WorkflowState.DEV_COMPLETE)
        self.task_router = DefaultRouter(self.target)
        self.policy = DefaultSimulationPolicy()

    def create_tasks(self, limit: int, store: Store):
        for i in range(limit):
            yield store.put(Task(task_name=f"Task {i}", story_points=1, initial_value=1))

    def create_developers(self, count: int):
        return [Developer(efficiency=1) for _ in range(count)]

    def test_developer_manager(self):
        self.env.process(self.create_tasks(5, self.source))

        self.env.run()
        self.assertEqual(len(self.source.items), 5)

        team = ResourceOperator(
            self.env, self.create_developers(2), workflow_policy=self.policy, resource_policy=self.policy, tracker=self.tracker)

        team.start(self.source, self.workflow_state, self.task_router)

        self.env.run()
        self.assertEqual(len(self.source.items), 0)
        self.assertEqual(len(self.target.items), 5)
        self.assertEqual(self.env.now, 3)

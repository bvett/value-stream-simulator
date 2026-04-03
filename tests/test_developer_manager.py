import unittest
from simpy import Environment, Store
from value_stream.resources import Developer
from value_stream.managers import DeveloperManager
from value_stream.task import Task
from value_stream import WorkflowState, WorkflowStateName

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloperManager(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.source = WorkflowState(self.env, WorkflowStateName.PENDING)
        self.target = WorkflowState(self.env, WorkflowStateName.DEV_COMPLETE)

    def create_tasks(self, limit: int, store: Store):
        for i in range(limit):
            yield store.put(Task(task_id=f"Task {i}", complexity=1, initial_value=1))

    def create_developers(self, count: int):
        return [Developer(1) for _ in range(count)]

    def test_developer_manager(self):
        self.env.process(self.create_tasks(5, self.source))

        self.env.run()
        self.assertEqual(len(self.source.items), 5)

        team = DeveloperManager(self.env, self.create_developers(2))

        team.start(self.source, self.target)

        self.env.run()
        self.assertEqual(len(self.source.items), 0)
        self.assertEqual(len(self.target.items), 5)
        self.assertEqual(self.env.now, 3)

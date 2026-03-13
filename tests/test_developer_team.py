import unittest
from simpy import Environment, Store
from value_stream.developer import Developer, DeveloperTeam
from value_stream.task import Task

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloperTeam(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.source = Store(self.env)
        self.target = Store(self.env)

    def create_tasks(self, count: int, store: Store):
        for _ in range(count):
            yield store.put(Task(complexity=1, initial_value=1))

    def create_developers(self, count: int):
        return [Developer(1) for _ in range(count)]

    def test_team(self):
        self.env.process(self.create_tasks(5, self.source))

        self.env.run()

        team = DeveloperTeam(self.env, self.create_developers(2))

        self.env.process(team.start(self.source, self.target))

        self.env.run()

        self.assertEqual(len(self.target.items), 5)
        self.assertEqual(self.env.now, 3)

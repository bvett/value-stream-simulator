import unittest

from simpy import Environment, Store

from value_stream.utils import TaskGenerator


class TestTaskGenerator(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.target = Store(self.env)

    def test_start(self):
        generator = TaskGenerator(story_points=1)

        generator.start(self.env, interval=1, target=self.target)

        self.env.run(10)

        generator.stop()

        self.assertEqual(len(self.target.items), 9)

    def test_multi(self):
        generator = TaskGenerator(group_size=3, story_points=1)

        generator.start(self.env, interval=1, target=self.target)

        self.env.run(10)

        generator.stop()

        self.assertEqual(len(self.target.items), 3 * 9)

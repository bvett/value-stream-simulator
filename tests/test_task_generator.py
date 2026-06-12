import unittest

from simpy import Environment, Store

from value_stream.utils import TaskFactory, TaskGenerator


class TestTaskGenerator(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.target = Store(self.env)

    def test_start(self):
        generator = TaskGenerator(factory=TaskFactory(
            story_points=1, initial_value=1), interval=1)

        generator.start(self.env, target=self.target)

        self.env.run(10)

        generator.stop()

        self.assertEqual(len(self.target.items), 9)

    def test_multi(self):
        generator = TaskGenerator(
            group_size=3, factory=TaskFactory(story_points=1, initial_value=1), interval=1)

        generator.start(self.env, target=self.target)

        self.env.run(10)

        generator.stop()

        self.assertEqual(len(self.target.items), 3 * 9)

    def test_limit(self):
        limit = 3
        generator = TaskGenerator(
            group_size=3, factory=TaskFactory(story_points=1, initial_value=1), interval=1, limit=3)

        generator.start(self.env, target=self.target)

        self.env.run()

        with self.assertRaises(RuntimeError):
            generator.stop()

        self.assertEqual(self.env.now, 3)
        self.assertEqual(len(self.target.items), 3 * limit)

    def test_validation(self):

        with self.assertRaises(ValueError):
            _ = TaskGenerator(factory=TaskFactory(
                story_points=1, initial_value=1), interval=0)

    def test_iteration(self):

        factory = TaskFactory(story_points=1, initial_value=1)

        batches = 5

        generator = TaskGenerator(factory=factory, interval=1)

        index = 1
        for task_group in generator:

            self.assertEqual(1, len(task_group))
            task = task_group[0]
            self.assertEqual(f"S{index}", task.task_id)

            index += 1
            if index == batches:
                break

        index = 1
        generator = TaskGenerator(factory=factory, interval=1, group_size=3)
        for task_group in generator:

            self.assertEqual(3, len(task_group))

            for i, task in enumerate(task_group):
                self.assertEqual(f"S{index}-{i+1}", task.task_id)

            index += 1
            if index == batches:
                break

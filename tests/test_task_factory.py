import unittest
import numpy as np
from simpy import Environment
from value_stream.utils.task_factory import TaskFactory
from value_stream.utils import generator_utils

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestTaskFactory(unittest.TestCase):

    def setUp(self) -> None:
        np.random.seed(1)

    def test_validation(self):

        factory = TaskFactory()
        with self.assertRaises(ValueError):
            factory.create(0)

        env = Environment()
        with self.assertRaises(ValueError):
            factory = TaskFactory(env=env, creation_time=3)

    def test_create_equal(self):
        factory = TaskFactory(story_points=2, initial_value=100)
        tasks_1 = factory.create(count=5, shuffle=False)
        tasks_2 = factory.create(count=5, shuffle=False)

        self.assertEqual(len(tasks_1), 5)

        for i, v in enumerate(tasks_1):
            self.assertEqual(v.task_id, tasks_2[i].task_id)

    def test_create_sd(self):
        factory = TaskFactory(story_points=generator_utils.uniform(
            1, 10), initial_value=3, depreciation_rate=.5,)

        tasks = factory.create(count=1, shuffle=False)

        self.assertEqual(tasks[0]._initial_value, 3)  # pylint: disable=W0212
        self.assertEqual(tasks[0].depreciation_rate, .5)

    def test_shuffle(self):
        factory = TaskFactory(story_points=2,
                              initial_value=100)

        tasks_1 = factory.create(count=5, shuffle=True)
        tasks_2 = factory.create(count=5, shuffle=True)

        mismatch = False
        for i, task in enumerate(tasks_1):
            mismatch |= task.task_id != tasks_2[i].task_id

        self.assertEqual(mismatch, True)

    def test_creation_time(self):
        factory = TaskFactory(
            story_points=1, initial_value=0, creation_time=42)
        task = factory.create(1)[0]
        self.assertEqual(42, task.creation_t)

        env = Environment()
        factory = TaskFactory(env=env, story_points=1, initial_value=1)
        for t in [1, 5, 7.5, 100]:
            env.run(t)
            task = factory.create(1)[0]
            self.assertEqual(t, task.creation_t)

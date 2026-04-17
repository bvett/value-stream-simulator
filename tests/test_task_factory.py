import unittest
import numpy as np
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

    def test_create_equal(self):
        factory = TaskFactory()
        tasks_1 = factory.create(
            count=5, complexity=2, initial_value=100, shuffle=False)
        tasks_2 = factory.create(
            count=5, complexity=2, initial_value=100, shuffle=False)

        self.assertEqual(len(tasks_1), 5)

        for i, v in enumerate(tasks_1):
            self.assertEqual(v.task_id, tasks_2[i].task_id)

    def test_create_sd(self):
        factory = TaskFactory()

        tasks = factory.create(count=1, complexity=generator_utils.uniform(
            1, 10), initial_value=3, depreciation_rate=.5, shuffle=False)

        self.assertEqual(tasks[0]._initial_value, 3)  # pylint: disable=W0212
        self.assertEqual(tasks[0].depreciation_rate, .5)

    def test_shuffle(self):
        factory = TaskFactory()

        tasks_1 = factory.create(count=5, complexity=2,
                                 initial_value=100, shuffle=True)
        tasks_2 = factory.create(count=5, complexity=2,
                                 initial_value=100, shuffle=True)

        mismatch = False
        for i, task in enumerate(tasks_1):
            mismatch |= task.task_id != tasks_2[i].task_id

        self.assertEqual(mismatch, True)

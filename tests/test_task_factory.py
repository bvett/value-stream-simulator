import unittest
import numpy as np
from value_stream.utils.task_factory import TaskFactory


class TestTaskFactory(unittest.TestCase):

    def setUp(self) -> None:
        np.random.seed(1)

    def test_validation(self):

        with self.assertRaises(ValueError):
            TaskFactory('_invalid_argument', complexity=0)  # type: ignore

        with self.assertRaises(ValueError):
            t = TaskFactory('sd', complexity=0)
            t.create(1)

        with self.assertRaises(ValueError):
            t = TaskFactory('equal', complexity=(1, 2))
            t.create(1)

    def test_create_equal(self):
        factory = TaskFactory('equal', complexity=2,
                              initial_value=100, shuffle=False)
        tasks_1 = factory.create(5)
        tasks_2 = factory.create(5)

        self.assertEqual(len(tasks_1), 5)

        for i, v in enumerate(tasks_1):
            self.assertEqual(v.task_id, tasks_2[i].task_id)

    def test_create_sd(self):
        factory = TaskFactory(strategy='sd', complexity=(1, 10),
                              initial_value=3, depreciation_rate=.5, shuffle=False)

        tasks = factory.create(1)

        self.assertEqual(tasks[0]._initial_value, 3)  # pylint: disable=W0212
        self.assertEqual(tasks[0].depreciation_rate, .5)

    def test_shuffle(self):
        factory = TaskFactory('equal', complexity=2,
                              initial_value=100, shuffle=True)

        tasks_1 = factory.create(5)
        tasks_2 = factory.create(5)

        mismatch = False
        for i, task in enumerate(tasks_1):
            mismatch |= task.task_id != tasks_2[i].task_id

        self.assertEqual(mismatch, True)

import unittest
from value_stream.task import Task


class TestTask(unittest.TestCase):

    def test_validation(self):

        # invalid initial_value
        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=-4.2, complexity=1.0)

        # invalid complexity
        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=4.2, complexity=-1)

        # invalid depreciatiom_rate
        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=1,
                 complexity=1, depreciation_rate=-1)

        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=1,
                 complexity=1, depreciation_rate=1.1)

        # invalid creation_time

        with self.assertRaises(ValueError):
            Task(task_id="", initial_value=100, complexity=1, creation_time=-1)

        # invalid time

        with self.assertRaises(ValueError):
            task = Task(task_id="", initial_value=100,
                        complexity=1, creation_time=5)
            task.value(4)

    def test_value(self):
        task = Task(task_id="",
                    initial_value=100,
                    complexity=1.0)

        self.assertEqual(task.value(), 100)

    def test_depreciation(self):

        # no depreciation
        task = Task(task_id="", initial_value=100,
                    complexity=1, depreciation_rate=0)

        for t in [0, 10, 200]:
            self.assertEqual(task.value(t), 100)

        # basic depreciation

        task = Task(task_id="", initial_value=100,
                    complexity=1, depreciation_rate=0.1)

        values = [100, 90, 81, 72.9]
        for i in range(0, 4):
            self.assertEqual(task.value(i), values[i])

        # depreciation with offset creation_time

        task = Task(task_id="", initial_value=100,
                    complexity=1, depreciation_rate=0.1, creation_time=5)

        values = [100, 90, 81, 72.9]
        for i, v in enumerate(range(5, 9)):
            self.assertEqual(task.value(v), values[i])

    def test_str(self):
        self.assertEqual(
            str(Task(task_id="foo", initial_value=0, complexity=1)), "foo")

    def test_loss(self):

        # No loss
        task = Task(task_id="", initial_value=50, complexity=1,
                    creation_time=0, depreciation_rate=0)

        task.history.delivery_start_t = 1
        task.history.delivery_end_t = 25

        self.assertEqual(task.loss(), 0)

        # Loss

        task = Task(task_id="", initial_value=50, complexity=1,
                    creation_time=0, depreciation_rate=0.1)

        task.history.delivery_start_t = 0
        task.history.delivery_end_t = 2

        self.assertEqual(task.loss(), -0.19)

    def test_delivered_value(self):

        # not delivered
        task = Task(task_id="", initial_value=100,
                    complexity=1, depreciation_rate=0.1)

        self.assertEqual(task.delivered_value(), 100)

        # default creation_time
        task.history.delivery_start_t = 2

        # ensure value does not change until delivered
        self.assertEqual(task.delivered_value(), 100)

        task.history.delivery_end_t = 2

        self.assertEqual(task.delivered_value(), 81)

        # offset creation_time

        task = Task(task_id="", initial_value=100, complexity=1,
                    depreciation_rate=0.1, creation_time=5)

        task.history.delivery_start_t = 5
        task.history.delivery_end_t = 5
        self.assertEqual(task.delivered_value(), 100)

        task.history.delivery_end_t = 6
        self.assertEqual(task.delivered_value(), 90)

        # validation
        task = Task(task_id="", initial_value=100, complexity=1,
                    depreciation_rate=0.1, creation_time=5)

        # missing delivery_start_t
        with self.assertRaises(ValueError):
            task.history.delivery_end_t = 5
            task.delivered_value()

        # inverted start/creation times
        with self.assertRaises(ValueError):
            task.history.delivery_start_t = 4
            task.delivered_value()

        # inverted start/end times
        with self.assertRaises(ValueError):
            task.history.delivery_start_t = 6
            task.history.delivery_end_t = 5
            task.delivered_value()

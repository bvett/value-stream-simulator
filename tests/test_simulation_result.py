import unittest
from unittest.mock import mock_open, patch

# from value_stream.utils import _dump_json
from value_stream.utils.task_factory import TaskFactory
from value_stream.developer import Developer
from value_stream.model import Model
from value_stream.simulation_result import SimulationResult


class TestSimulationResult(unittest.TestCase):

    def setUp(self) -> None:
        self.developer_team = [Developer(1.0)]

    def create_tasks(self, count: int):

        tasks = TaskFactory(
            strategy='equal', complexity=3, initial_value=50, depreciation_rate=0.015, shuffle=False).create(count)

        for i, task in enumerate(tasks):
            task.history.delivery_start_t = i
            task.history.delivery_end_t = i

        return tasks

    def test_delivered_value(self):
        NUM_TASKS = 10
        tasks = self.create_tasks(NUM_TASKS)

        expected_delivered_values = []
        for task in tasks:
            expected_delivered_value = task._initial_value * \
                ((1-task.depreciation_rate) **
                 task.history.delivery_end_t)  # type: ignore

            expected_delivered_values.append(expected_delivered_value)

        model_result = SimulationResult(
            Model(self.developer_team, 1, 1, 1), tasks)

        self.assertEqual(sum(expected_delivered_values),
                         model_result.delivered_value())

    def test_loss(self):
        NUM_TASKS = 10
        tasks = self.create_tasks(NUM_TASKS)

        expected_losses = []
        for task in tasks:
            expected_delivered_value = task._initial_value * \
                ((1-task.depreciation_rate) **
                 task.history.delivery_end_t)  # type: ignore

            expected_losses.append(
                (expected_delivered_value / task._initial_value) - 1)

        model_result = SimulationResult(
            Model(self.developer_team, 1, 1, 1), tasks)

        self.assertAlmostEqual(sum(expected_losses)/NUM_TASKS,
                               model_result.loss())

    # @patch('builtins.open', new_callable=mock_open)
    # def test_to_json(self, mock_file):

    #    NUM_TASKS = 10
    #    tasks = self.create_tasks(NUM_TASKS)

    #    model_result = SimulationResult(
    #        Model(self.developer_team, 1, 1, 1), tasks)

    #    _dump_json([model_result], "mockfile.json")

    #    mock_file.assert_called_once_with(
    #        "mockfile.json", "w", encoding='utf-8')

import math
import unittest
from unittest.mock import patch

from tqdm import tqdm

from value_stream import Simulation
from value_stream.utils import DeveloperFactory, ModelFactory, ResultViewer, TaskFactory

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestResultViewer(unittest.TestCase):

    def setUp(self):
        simulation = Simulation()

        self.num_tasks = 10
        self.team_size = 5
        self.max_cadence = 7

        developer_factory = DeveloperFactory(efficiency=1.0)

        developer_teams = [developer_factory.create(
            team_size) for team_size in range(1, self.team_size+1)]

        self.num_teams = len(developer_teams)

        models = ModelFactory(toolchain_concurrency=2,
                              deployment_duration=.25,
                              developer_factory=developer_factory).create(
            teams=range(1, self.team_size+1),
            deployment_cadences=range(self.max_cadence, -1, -1),
            num_qa_resources=5)

        tasks = TaskFactory(complexity=1.0).create(self.num_tasks)

        self.model_results = simulation.execute(
            tasks=tasks, models=models)

        self.pbar = tqdm(self.model_results)

    @patch('matplotlib.pyplot.show')
    @patch('tqdm.tqdm.update')
    def test_plot_loss_vs_cadence(self, mock_tqdm_update, mock_pyplot_show):
        ResultViewer(self.model_results, pbar=self.pbar).loss_vs_cadence(
            team_samples=self.team_size)

        mock_pyplot_show.assert_called_once()
        mock_tqdm_update.assert_called()

    @patch('matplotlib.pyplot.show')
    def test_plot_time_alloc_by_cadence(self, mock_pyplot_show):
        ResultViewer(self.model_results).time_alloc_vs_cadence(
            nrows=4, ncols=3)

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_plot_delivery_timeline(self, mock_pyplot_show):

        ResultViewer(self.model_results).delivery_timeline(
            cadence=self.max_cadence, team_size=self.team_size)

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_plot_delivered_value(self, mock_pyplot_show):

        ResultViewer(self.model_results).delivered_value_vs_time(
            cadence=self.max_cadence, team_samples=math.ceil(self.num_teams/2))

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_plot_team_size_vs_delivery(self, mock_pyplot_show):
        ResultViewer(self.model_results).delivered_value_vs_team_size(
            cadence_samples=self.max_cadence)

        mock_pyplot_show.assert_called_once()

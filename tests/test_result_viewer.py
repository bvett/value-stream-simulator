import unittest
from unittest.mock import patch

from value_stream.client import SimulationRunner
from value_stream.client.views import ResultViewer
from value_stream.resources import QATester, Toolchain, DeveloperFactory
from value_stream.simulation import ModelFactory
from value_stream.task import TaskFactory

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestResultViewer(unittest.TestCase):

    def setUp(self):
        simulation = SimulationRunner()

        self.num_tasks = 10
        self.team_size = 5
        self.max_cadence = 7

        developer_factory = DeveloperFactory()

        developer_teams = [developer_factory.create(
            team_size, efficiency=1.0) for team_size in range(1, self.team_size+1)]

        self.num_teams = len(developer_teams)

        qa_tester_pool = QATester.create_pool(limit=5)
        toolchain_pool = Toolchain.create_pool(
            limit=2, deployment_duration=.25)

        models = ModelFactory().create(
            teams=developer_teams,
            deployment_cadences=range(self.max_cadence, -1, -1),
            qa_testers=qa_tester_pool,
            toolchain_pool=toolchain_pool,
            support_intervals=[None])

        tasks = TaskFactory(initial_value=1,
                            depreciation_rate=0, story_points=1.0).create(count=self.num_tasks)

        self.simulation_results = simulation.execute(
            tasks=tasks, models=models)

    @patch('matplotlib.pyplot.show')
    def test_loss_vs_cadence(self, mock_pyplot_show):
        ResultViewer(self.simulation_results).loss_vs_cadence()

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_loss_vs_team_size(self, mock_pyplot_show):

        ResultViewer(self.simulation_results).loss_vs_team_size()

        mock_pyplot_show.assert_called_once()

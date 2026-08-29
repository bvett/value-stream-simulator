import unittest
from unittest.mock import patch

from value_stream import SimulationRunner
from value_stream.client.views import MetadataViewer
from value_stream.resources import QATester, Toolchain
from value_stream.utils import DeveloperFactory, ModelFactory, TaskFactory


class TestMetadataViewer(unittest.TestCase):
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
    def test_mean_stage_loss(self, mock_pyplot_show):
        MetadataViewer(self.simulation_results).mean_stage_loss()

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_resource_utilization(self, mock_pyplot_show):
        MetadataViewer(self.simulation_results).resource_utilization()

        mock_pyplot_show.assert_called_once()

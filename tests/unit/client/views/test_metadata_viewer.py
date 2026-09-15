import unittest
from unittest.mock import patch

import numpy as np

from value_stream.client import SimulationRunner
from value_stream.client.views import MetadataViewer
from value_stream.resources import QATester, Toolchain
from value_stream.simulation import ModelFactory
from value_stream.factory import DeveloperFactory, TaskFactory


class TestMetadataViewer(unittest.TestCase):
    def setUp(self):
        simulation = SimulationRunner()

        self.num_tasks = 10
        self.team_size = 5
        self.team_size_samples = 3
        self.max_cadence = 7
        self.cadence_samples = 3

        developer_teams = [DeveloperFactory.create(
            team_size, efficiency=1.0) for team_size in np.linspace(1, self.team_size, self.team_size_samples, dtype=int)]

        self.num_teams = len(developer_teams)

        qa_tester_pool = QATester.create_pool(limit=5)
        toolchain_pool = Toolchain.create_pool(
            limit=2, deployment_duration=.25)

        models = ModelFactory.create(
            teams=developer_teams,
            deployment_cadences=np.linspace(
                0, self.max_cadence, self.cadence_samples, dtype=int),
            qa_testers=qa_tester_pool,
            toolchain_pool=toolchain_pool,
            support_intervals=[None])

        tasks = TaskFactory(initial_value=1,
                            depreciation_rate=0, story_points=1.0).create(count=self.num_tasks)

        self.simulation_results = simulation.execute(
            tasks=tasks, models=models)

    @patch('matplotlib.pyplot.show')
    def test_mean_stage_loss(self, mock_pyplot_show):
        MetadataViewer(self.simulation_results,
                       task_states=SimulationRunner().task_states()).mean_stage_loss()

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_resource_utilization(self, mock_pyplot_show):
        MetadataViewer(self.simulation_results, task_states=SimulationRunner(
        ).task_states()).resource_utilization()

        mock_pyplot_show.assert_called_once()

    @patch('matplotlib.pyplot.show')
    def test_resource_capacity(self, mock_pyplot_show):
        MetadataViewer(self.simulation_results, task_states=SimulationRunner(
        ).task_states()).resource_capacity()

        mock_pyplot_show.assert_called_once()

import unittest
from unittest.mock import patch
from tqdm import tqdm
from value_stream.client import SimulationRunner
from value_stream.resources import QATester, Toolchain
from value_stream.simulation import ModelFactory
from value_stream.factories import DeveloperFactory, TaskFactory

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestSimulationRunner(unittest.TestCase):

    @patch('value_stream.simulation.Simulation.execute')
    def test_all(self, mock_simulation_execute):

        NUM_TASKS = 10
        NUM_DEVELOPERS = 2
        MAX_CADENCE = 5
        SUPPORT_INTERVAL = 4

        simulation_runner = SimulationRunner()

        teams = [DeveloperFactory.create(
            count=NUM_DEVELOPERS, efficiency=1.0)]

        qa_tester_pool = QATester.create_pool(limit=1)
        toolchain_pool = Toolchain.create_pool(
            limit=2, deployment_duration=.25)

        models = ModelFactory.create(
            teams=teams,
            deployment_cadences=range(MAX_CADENCE, -1, -1),
            qa_testers=qa_tester_pool,
            toolchain_pool=toolchain_pool,
            support_intervals=[SUPPORT_INTERVAL])

        tasks = TaskFactory(initial_value=1,
                            depreciation_rate=0,
                            story_points=1.0).create(count=NUM_TASKS)

        with tqdm(total=len(models)) as pbar:
            _ = simulation_runner.execute(
                tasks=tasks,
                models=models,
                pbar=pbar)

        self.assertEqual(mock_simulation_execute.call_count, len(models))

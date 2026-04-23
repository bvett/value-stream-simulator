import unittest
from tqdm import tqdm
from value_stream.resources import QATesterPool, ToolchainPool
from value_stream.simulation import Simulation
from value_stream.utils import DeveloperFactory, ModelFactory, TaskFactory

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestSimulation(unittest.TestCase):

    def test_all(self):

        NUM_TASKS = 10
        NUM_DEVELOPERS = 2
        MAX_CADENCE = 5

        simulation = Simulation()

        teams = [DeveloperFactory().create(
            count=NUM_DEVELOPERS, efficiency=1.0)]

        qa_tester_pool = QATesterPool(limit=1)
        toolchain_pool = ToolchainPool(limit=2, deployment_duration=.25)

        models = ModelFactory().create(
            teams=teams,
            deployment_cadences=range(MAX_CADENCE, -1, -1),
            qa_testers=qa_tester_pool,
            toolchain_pool=toolchain_pool)

        tasks = TaskFactory().create(count=NUM_TASKS, complexity=1.0)

        with tqdm(total=len(models)) as pbar:
            model_results = simulation.execute(
                tasks=tasks, models=models, pbar=pbar)

        # one result for every combination of task and cadence
        self.assertEqual(len(model_results), NUM_TASKS * (MAX_CADENCE+1))

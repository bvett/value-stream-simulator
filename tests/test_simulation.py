import unittest
from tqdm import tqdm
from value_stream.simulation import Simulation
from value_stream.utils import DeveloperFactory, ModelFactory, TaskFactory


class TestSimulation(unittest.TestCase):

    def test_all(self):

        NUM_TASKS = 10

        simulation = Simulation()

        developer_team = DeveloperFactory('equal', 1.0).create(2)
        models = ModelFactory(2, .25).create(
            [developer_team], range(5, -1, -1))

        tasks = TaskFactory('equal', 1.0).create(NUM_TASKS)

        with tqdm(total=len(models)) as pbar:
            model_results = simulation.execute(
                tasks=tasks, models=models, pbar=pbar)

        self.assertEqual(len(model_results), 6)

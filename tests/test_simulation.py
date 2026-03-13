import unittest
from tqdm import tqdm
from value_stream.simulation import Simulation
from value_stream.utils import DeveloperFactory, ModelFactory, TaskFactory

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestSimulation(unittest.TestCase):

    def test_all(self):

        NUM_TASKS = 10
        NUM_DEVELOPERS = 2
        MAX_CADENCE = 5

        simulation = Simulation()

        developer_team = DeveloperFactory('equal', 1.0).create(NUM_DEVELOPERS)
        models = ModelFactory(2, .25).create(
            [developer_team], range(MAX_CADENCE, -1, -1))

        tasks = TaskFactory('equal', 1.0).create(NUM_TASKS)

        with tqdm(total=len(models)) as pbar:
            model_results = simulation.execute(
                tasks=tasks, models=models, pbar=pbar)

        # one result for every combination of task and cadence
        self.assertEqual(len(model_results), NUM_TASKS * (MAX_CADENCE+1))

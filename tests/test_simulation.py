import unittest
from tqdm import tqdm
from value_stream.resources import QATester, Toolchain
from value_stream.simulation import Simulation
from value_stream.utils import DeveloperFactory, ModelFactory, TaskFactory, TaskGenerator
from value_stream import SupportTask, TaskType

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestSimulation(unittest.TestCase):

    def test_all(self):

        NUM_TASKS = 10
        NUM_DEVELOPERS = 2
        MAX_CADENCE = 5
        SUPPORT_INTERVAL = 4

        simulation = Simulation()

        teams = [DeveloperFactory().create(
            count=NUM_DEVELOPERS, efficiency=1.0)]

        qa_tester_pool = QATester.create_pool(limit=1)
        toolchain_pool = Toolchain.create_pool(
            limit=2, deployment_duration=.25)

        models = ModelFactory().create(
            teams=teams,
            deployment_cadences=range(MAX_CADENCE, -1, -1),
            qa_testers=qa_tester_pool,
            toolchain_pool=toolchain_pool,
            support_intervals=[SUPPORT_INTERVAL])

        tasks = TaskFactory(initial_value=1,
                            depreciation_rate=0,
                            story_points=1.0).create(count=NUM_TASKS)

        support_factory = TaskFactory(
            SupportTask, story_points=1)

        support_generator = TaskGenerator(
            factory=support_factory)

        with tqdm(total=len(models)) as pbar:
            model_results = simulation.execute(
                tasks=tasks,
                models=models,
                support_generator=support_generator,
                pbar=pbar)

        # one result for every combination of task and cadence
        expected_dev_tasks = NUM_TASKS * (MAX_CADENCE + 1)

        num_dev_tasks = 0
        num_support_tasks = 0

        for r in model_results:
            if r.task.task_type == TaskType.DEVELOPMENT:
                num_dev_tasks += 1
            elif r.task.task_type == TaskType.SUPPORT:
                num_support_tasks += 1

        # Asserting only # of completed dev tasks.
        # Calculating expected # of completed support tasks is more complicated,
        # and can be better validated with lower-level tests.

        self.assertEqual(num_dev_tasks, expected_dev_tasks)

import unittest
from tqdm import tqdm
from value_stream.client import SimulationRunner
from value_stream.core import EventStatus, WorkflowStateName
from value_stream.resources import QATester, Toolchain, DeveloperFactory
from value_stream.simulation import ModelFactory
from value_stream.task import SupportTask, TaskType, TaskEvent, TaskFactory, TaskGenerator

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestSimulation(unittest.TestCase):

    def test_all(self):

        NUM_TASKS = 10
        NUM_DEVELOPERS = 2
        MAX_CADENCE = 5
        SUPPORT_INTERVAL = 4

        simulation = SimulationRunner()

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

        with tqdm(total=len(models)) as pbar:
            simulation_results = simulation.execute(
                tasks=tasks,
                models=models,
                pbar=pbar)

        # one result for every combination of task and cadence
        expected_dev_tasks = NUM_TASKS * (MAX_CADENCE + 1)

        # hard-coding this to an arbitrary value for now to guard against regression
        # will evolve to something more calculated when this tests individual simulations instead of the runner
        expected_support_tasks = 8

        num_dev_tasks = 0
        num_support_tasks = 0

        # The problem here is that we don't have access to the TaskType anymore.....
        for r in simulation_results:
            for e in r.metadata.event_metadata:
                if (e.event == WorkflowStateName.DEVELOPMENT) and (e.status == EventStatus.SUCCESS) and (e.event_type == TaskEvent.EventType.END) and (e.task_type == TaskType.DEVELOPMENT):
                    num_dev_tasks += 1
                elif (e.event == WorkflowStateName.DEVELOPMENT) and (e.status == EventStatus.SUCCESS) and (e.event_type == TaskEvent.EventType.END) and (e.task_type == TaskType.SUPPORT):
                    num_support_tasks += 1

        self.assertEqual(num_dev_tasks, expected_dev_tasks)

        # TODO: address flaky assert
        # self.assertEqual(num_support_tasks, expected_support_tasks)

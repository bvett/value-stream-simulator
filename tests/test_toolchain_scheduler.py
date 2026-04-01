import unittest
from simpy import Environment, Store
from value_stream.workflow_state_name import WorkflowStateName
from value_stream.task import Task
from value_stream.resources import Toolchain
from value_stream.managers import ToolchainManager
from value_stream.workflow_state import WorkflowState, TerminalWorkflowState

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestToolchainScheduler(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.source = WorkflowState(self.env, WorkflowStateName.DEV_COMPLETE)
        self.target = TerminalWorkflowState(
            self.env, WorkflowStateName.DELIVERY)

    def test_validation(self):

        with self.assertRaises(ValueError):
            next(Toolchain.create(deployment_duration=-1, limit=10))

        self.assertIsNotNone(
            next(Toolchain.create(deployment_duration=0, limit=5)))

    def test_noop_deployment(self):
        tasks = []

        target = WorkflowState(self.env, WorkflowStateName.DEPLOYMENT)

        toolchain = Toolchain(
            deployment_duration=0)
        self.env.process(toolchain.operate(self.env, tasks, target))

        self.env.run()

        self.assertEqual(len(target.items), 0)

    def test_batch_deployment(self):

        tasks = []

        NUM_TASKS = 5
        DEPLOYMENT_DURATION = 0.5

        for _ in range(NUM_TASKS):
            tasks.append(
                Task(complexity=1, initial_value=1))

        toolchain = Toolchain(deployment_duration=DEPLOYMENT_DURATION)

        self.env.process(toolchain.operate(self.env, tasks, self.target))

        self.env.run()

        self.assertEqual(len(self.target.items), NUM_TASKS)
        self.assertEqual(self.env.now, DEPLOYMENT_DURATION)

        for task in tasks:
            self.assertEqual(task.history.duration(
                WorkflowStateName.DEPLOYMENT), DEPLOYMENT_DURATION)

    def test_serial_deployment(self):

        NUM_TASKS = 5
        DEPLOYMENT_DURATION = 0.5

        toolchain = ToolchainManager(self.env, Toolchain.create(deployment_duration=DEPLOYMENT_DURATION, limit=1),
                                     deployment_cadence=1)

        for _ in range(NUM_TASKS):
            yield self.source.put(Task(complexity=1, initial_value=1))

        # for _ in range(NUM_TASKS):
        #    self.env.process(toolchain._do_deployment(
        #        [Task(complexity=1, initial_value=1)], self.target))

        self.env.run()

        toolchain.start(self.source, self.target)
        self.env.run()

        self.assertEqual(len(self.target.items), NUM_TASKS)

        self.assertEqual(self.env.now, NUM_TASKS * DEPLOYMENT_DURATION)

    def create_tasks(self, count: int, store: Store):
        for _ in range(count):
            yield store.put(Task(complexity=1, initial_value=1))

    def run_scenario(self, num_tasks: int,
                     deployment_duration: float,
                     cadence: int,
                     concurrency: int):

        self.env.process(self.create_tasks(num_tasks, self.source))

        self.env.run()

        toolchain = ToolchainManager(
            self.env, Toolchain.create(deployment_duration=deployment_duration, limit=concurrency), cadence)

        toolchain.start(self.source, self.target)

        self.assertEqual(len(self.source.items), num_tasks)

        self.env.run(until=10)

        self.assertEqual(len(self.target.items), num_tasks)

    def test_scenario_1(self):
        # Continuous delivery, no concurrency

        self.run_scenario(num_tasks=5,
                          deployment_duration=.25,
                          cadence=0,
                          concurrency=1)

        self.assertEqual(
            max([i.delivered_time() for i in self.target.items]), 1.25)

    def test_scenario_2(self):
        # Continuous delivery, with concurrency

        self.run_scenario(num_tasks=5,
                          deployment_duration=.25,
                          cadence=0,
                          concurrency=2)

        self.assertEqual(
            max([i.delivered_time() for i in self.target.items]), 0.75)

    def test_scenario_3(self):
        # Regular delivery, no concurrency

        self.run_scenario(num_tasks=5,
                          deployment_duration=.25,
                          cadence=2,
                          concurrency=1)

        self.assertEqual(
            max([i.delivered_time() for i in self.target.items]), 2.25)

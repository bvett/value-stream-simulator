import unittest

from simpy import Environment

from value_stream import DefaultSimulationPolicy
from value_stream import WorkflowState, WorkflowStateName
from value_stream.utils import DeveloperFactory
from value_stream.resources import ResourceOperator


class TestResourceOperator(unittest.TestCase):
    def setUp(self):
        self.env = Environment()

        self.resources = DeveloperFactory().create(3)

        self.source = WorkflowState(self.env, WorkflowStateName.PENDING)
        self.target = WorkflowState(self.env, WorkflowStateName.DELIVERY)

        self.policy = DefaultSimulationPolicy()

    def test_validation(self):

        # catch negative cadence
        with self.assertRaises(ValueError):
            _ = ResourceOperator(env=self.env,
                                 resources=self.resources,
                                 cadence=-1,
                                 policy=self.policy)

        # attempt to start twice in succession
        with self.assertRaises(RuntimeError):
            manager = ResourceOperator(env=self.env,
                                       resources=self.resources,
                                       policy=self.policy)

            for _ in range(2):
                manager.start(source=self.source,
                              target=self.target)

        # attempt to start after stopping
        with self.assertRaises(RuntimeError):
            manager = ResourceOperator(env=self.env,
                                       resources=self.resources,
                                       policy=self.policy)
            for _ in range(2):
                manager.start(source=self.source,
                              target=self.target)

                manager.stop()

        # attempt to stop a manager that has not been started
        with self.assertRaises(RuntimeError):
            manager = ResourceOperator(env=self.env,
                                       resources=self.resources,
                                       policy=self.policy)

            manager.stop()

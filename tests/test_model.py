import unittest
from value_stream.resources import Developer, QATesterPool, ToolchainPool
from value_stream.model import Model

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestModel(unittest.TestCase):

    def setUp(self):
        self.developer_team = [Developer(1.0)]

    def test_validation(self):

        _ = Model(developer_team=self.developer_team,
                  deployment_cadence=0,
                  qa_testers=QATesterPool(limit=5),
                  toolchain_pool=ToolchainPool(limit=None, deployment_duration=0))

        with self.assertRaises(ValueError):
            Model(self.developer_team,
                  deployment_cadence=-1,
                  qa_testers=QATesterPool(limit=1),
                  toolchain_pool=ToolchainPool(limit=0, depployment_duration=0))

        with self.assertRaises(ValueError):
            Model(self.developer_team,
                  deployment_cadence=0,
                  qa_testers=QATesterPool(limit=1),
                  toolchain_pool=ToolchainPool(limit=-1, deployment_duration=0))

        with self.assertRaises(ValueError):
            Model(self.developer_team,
                  deployment_cadence=0,
                  qa_testers=QATesterPool(limit=1),
                  toolchain_pool=ToolchainPool(limit=0, deployment_duration=-1))

        with self.assertRaises(ValueError):
            Model(self.developer_team,
                  deployment_cadence=0,
                  qa_testers=QATesterPool(limit=0),
                  toolchain_pool=ToolchainPool(limit=0, deployment_duration=0))

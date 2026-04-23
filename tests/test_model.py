import unittest
from value_stream.resources import Developer, QATesterPool, ToolchainPool
from value_stream.model import Model

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestModel(unittest.TestCase):

    def setUp(self):
        self.developer_team = [Developer(1.0)]

        self.qa_tester_pool = QATesterPool(limit=5)
        self.toolchain_pool = ToolchainPool(limit=None, deployment_duration=0)

    def test_validation(self):

        _ = Model(developer_team=self.developer_team,
                  deployment_cadence=0,
                  qa_testers=self.qa_tester_pool,
                  toolchain_pool=self.toolchain_pool)

        with self.assertRaises(ValueError):
            Model(self.developer_team,
                  deployment_cadence=-1,
                  qa_testers=self.qa_tester_pool,
                  toolchain_pool=self.toolchain_pool)

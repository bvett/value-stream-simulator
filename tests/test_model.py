import unittest
from value_stream.resources import Developer, QATesterPool
from value_stream.model import Model

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestModel(unittest.TestCase):

    def setUp(self):
        self.developer_team = [Developer(1.0)]

    def test_validation(self):

        _ = Model(developer_team=self.developer_team,
                  toolchain_concurrency=0, deployment_duration=0, deployment_cadence=0,
                  qa_testers=QATesterPool(limit=5).create())

        with self.assertRaises(ValueError):
            Model(self.developer_team, -1, 0, 0,
                  qa_testers=QATesterPool(limit=1).create())

        with self.assertRaises(ValueError):
            Model(self.developer_team, 0, -1, 0,
                  qa_testers=QATesterPool(limit=1).create())

        with self.assertRaises(ValueError):
            Model(self.developer_team, 0, 0, -1,
                  qa_testers=QATesterPool(limit=1).create())

        with self.assertRaises(ValueError):
            Model(self.developer_team, 0, 0, 0,
                  qa_testers=QATesterPool(limit=0).create())

import unittest
from value_stream.developer import Developer
from value_stream.model import Model


class TestModel(unittest.TestCase):

    def setUp(self):
        self.developer_team = [Developer(1.0)]

    def test_model(self) -> None:

        model = Model(developer_team=self.developer_team,
                      toolchain_concurrency=0, deployment_duration=0, deployment_cadence=0)

        s = str(model)

        self.assertNotEqual(s, "")

    def test_validation(self):

        with self.assertRaises(ValueError):
            Model(self.developer_team, -1, 0, 0)

        with self.assertRaises(ValueError):
            Model(self.developer_team, 0, -1, 0)

        with self.assertRaises(ValueError):
            Model(self.developer_team, 0, 0, -1)

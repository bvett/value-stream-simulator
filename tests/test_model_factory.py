from typing import Collection
import unittest
from value_stream.resources import Developer
from value_stream.utils.developer_factory import DeveloperFactory
from value_stream.utils.model_factory import ModelFactory

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestModelFactory(unittest.TestCase):

    def test_create(self):

        developer_factory = DeveloperFactory()
        factory = ModelFactory(toolchain_concurrency=2,
                               deployment_duration=4.5)

        NUM_CADENCES = 3
        cadences = range(NUM_CADENCES)

        NUM_TEAMS = 4

        teams: list[Collection[Developer]] = []

        for i in range(1, NUM_TEAMS+1):
            teams.append(developer_factory.create(i))

        models = factory.create(teams=teams,
                                deployment_cadences=cadences, num_qa_resources=5)

        self.assertEqual(len(models), NUM_TEAMS * NUM_CADENCES)
        for model in models:
            self.assertIn(model.deployment_cadence, cadences)
            self.assertEqual(model.deployment_duration, 4.5)
            self.assertEqual(model.toolchain_concurrency, 2)

import unittest
import numpy as np
from value_stream.factory import DeveloperFactory
from value_stream.utils import generator_utils

# pylint:disable=missing-class-docstring,missing-function-docstring


class TestDeveloperFactory(unittest.TestCase):

    def setUp(self):
        np.random.seed(1)

    def test_validation(self):

        with self.assertRaises(ValueError):
            _ = DeveloperFactory.create(0)

        with self.assertRaises(ValueError):
            _ = DeveloperFactory.create(-1)

    def test_create_equal(self):

        devs_1 = DeveloperFactory.create(5, efficiency=1.2)
        devs_2 = DeveloperFactory.create(5, efficiency=1.2)

        for i, dev in enumerate(devs_1):
            self.assertEqual(dev.name, devs_2[i].name)
            self.assertEqual(dev.efficiency, 1.2)

    def test_create_sd(self):

        DeveloperFactory.create(5, efficiency=generator_utils.uniform(.5, 1.5))

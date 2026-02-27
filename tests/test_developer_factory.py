import unittest
import numpy as np
from value_stream.utils.developer_factory import DeveloperFactory


class TestDeveloperFactory(unittest.TestCase):

    def setUp(self):
        np.random.seed(1)

    def test_validation(self):

        with self.assertRaises(ValueError):
            DeveloperFactory('_invalid_argument', efficiency=1)  # type: ignore

        with self.assertRaises(ValueError):
            factory = DeveloperFactory('equal', efficiency=(1, 2))
            factory.create(1)

        with self.assertRaises(ValueError):
            factory = DeveloperFactory('sd', efficiency=1)
            factory.create(1)

        with self.assertRaises(ValueError):
            factory = DeveloperFactory('equal', efficiency=1)
            factory.create(-1)

    def test_create_equal(self):

        factory = DeveloperFactory('equal', 1.2)

        devs_1 = factory.create(5)
        devs_2 = factory.create(5)

        for i, dev in enumerate(devs_1):
            self.assertEqual(dev.name, devs_2[i].name)
            self.assertEqual(dev.efficiency, 1.2)

    def test_create_sd(self):

        factory = DeveloperFactory('sd', (.5, 1.5))
        factory.create(5)

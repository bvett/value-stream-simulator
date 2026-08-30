import unittest
from simpy import Environment

from value_stream.core import Epoch


class TestEpoch(unittest.TestCase):
    def test_init(self):
        env = Environment()

        epoch_1 = Epoch(env.now)

        self.assertEqual(0, epoch_1._offset_t)

        env.run(until=10)

        epoch_2 = Epoch(env.now)

        self.assertEqual(0, epoch_1._offset_t)
        self.assertEqual(10, epoch_2._offset_t)

    def test_time(self):

        env = Environment()
        epoch_1 = Epoch(env.now)
        env.run(until=50)
        epoch_2 = Epoch(env.now)

        with self.assertRaises(ValueError):
            epoch_1.to_epoch_time(-1)

        with self.assertRaises(ValueError):
            epoch_2.to_epoch_time(-49)

        self.assertEqual(0, epoch_1.to_epoch_time(0))
        self.assertEqual(100, epoch_1.to_epoch_time(100))

        self.assertEqual(0, epoch_2.to_epoch_time(50))
        self.assertEqual(50, epoch_2.to_epoch_time(100))

        self.assertEqual(200, epoch_1.to_sim_time(200))
        self.assertEqual(250, epoch_2.to_sim_time(200))

        self.assertEqual(50, epoch_2.to_sim_time(0))

        with self.assertRaises(ValueError):
            epoch_1.to_sim_time(-1)

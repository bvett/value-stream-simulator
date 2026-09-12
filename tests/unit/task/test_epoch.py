import unittest
from simpy import Environment

from value_stream.task import Epoch, Task


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

    def test_start_epoch(self):

        t1 = Task(initial_value=1, story_points=1, creation_sim_t=10)
        t2 = Task(initial_value=1, story_points=1, creation_sim_t=11)

        initial_tasks = [t1, t2]
        env_time = 15
        env = Environment(initial_time=env_time)

        tasks = Task.start_epoch(tasks=initial_tasks, env=env)

        self.assertEqual(10, t1.creation_sim_t)
        self.assertEqual(11, t2.creation_sim_t)

        for t in tasks:
            self.assertEqual(t.creation_sim_t, env_time)

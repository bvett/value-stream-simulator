import unittest

from simpy import Environment, Store, Interrupt

from value_stream.task import Task
from value_stream.simulation.factory import TaskFactory, TaskGenerator


class TestTaskGenerator(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.target = Store(self.env)

    def test_start(self):
        generator = TaskGenerator(factory=TaskFactory(
            story_points=1, initial_value=1))

        generator.start(self.env, target=self.target, interval=1)

        self.env.run(10)

        generator.stop()

        self.assertEqual(len(self.target.items), 9)

    def test_multi(self):
        generator = TaskGenerator(
            group_size=3, factory=TaskFactory(story_points=1, initial_value=1))

        generator.start(self.env, target=self.target, interval=1)

        self.env.run(10)

        generator.stop()

        self.assertEqual(len(self.target.items), 3 * 9)

    def test_limit(self):
        limit = 3
        generator = TaskGenerator(
            group_size=3, factory=TaskFactory(story_points=1, initial_value=1), limit=3)

        generator.start(self.env, target=self.target, interval=1)

        self.env.run()

        with self.assertRaises(RuntimeError):
            generator.stop()

        self.assertEqual(self.env.now, 3)
        self.assertEqual(len(self.target.items), 3 * limit)

    def test_validation(self):

        with self.assertRaises(ValueError):
            TaskGenerator(factory=TaskFactory(
                story_points=1, initial_value=1)).start(self.env, self.target, interval=0)

    def test_creation_time(self):

        # validates correct creation/epoch_times in generated Tasks

        starting_t = 15
        group_size = 2
        interval = 3
        num_intervals = 2

        factory = TaskFactory(initial_value=1, story_points=1)

        generator = TaskGenerator(factory=factory, group_size=group_size)

        # advance sim time away from 0
        self.env.run(starting_t)

        def monitor(e: Environment, s: Store, times: list[float], tasks: list[Task]):

            while True:

                try:
                    task = yield s.get()
                    times.append(e.now)
                    tasks.append(task)
                except Interrupt:
                    break

        generator.start(self.env, target=self.target, interval=interval)
        actual_creation_times: list[float] = []
        generated_tasks: list[Task] = []

        self.env.process(
            monitor(self.env, self.target, times=actual_creation_times, tasks=generated_tasks))

        self.env.run(1 + starting_t + (interval * num_intervals))

        self.assertEqual(group_size * num_intervals, len(generated_tasks))

        expected_creation_times = [18, 18, 21, 21]

        for k, v in enumerate(generated_tasks):
            task: Task = v
            self.assertEqual(expected_creation_times[k], task.creation_sim_t)

            self.assertEqual(
                expected_creation_times[k], task.history.epoch.to_sim_time(0))

            self.assertEqual(task._initial_value, task.value(
                task.history.epoch.to_epoch_time(expected_creation_times[k])))

        self.assertListEqual(expected_creation_times, actual_creation_times)

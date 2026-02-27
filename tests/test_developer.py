import unittest
from simpy import Environment, Store
from value_stream.developer import Developer
from value_stream.task import Task


class TestDeveloper(unittest.TestCase):

    def setUp(self):

        self.simple_task = Task(task_id="", initial_value=1, complexity=.6)
        self.complex_task = Task(task_id="", initial_value=1, complexity=2)

    def test_validation(self):

        with self.assertRaises(ValueError):
            Developer(0)

        with self.assertRaises(ValueError):
            Developer(-1)

    def test_developer(self):

        junior_developer = Developer(.5, name="junior")
        senior_developer = Developer(1.5, name="senior")

        env = Environment()
        target = Store(env)

        for dev in [junior_developer, senior_developer]:
            for task in [self.simple_task, self.complex_task]:
                env.process(dev.develop(env, task, target))

        env.run()

        for i, v in enumerate([0.4, 1.2, 1.3333333, 4]):
            self.assertAlmostEqual(target.items[i].history.dev_end_t, v)
            self.assertEqual(target.items[i].history.dev_start_t, 0)

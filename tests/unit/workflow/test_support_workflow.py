import unittest

from simpy import Environment

from value_stream.workflow import SupportWorkflow, TaskStore, SDLCWorkflow


class TestSupportWorkflow(unittest.TestCase):

    def setUp(self):
        self.env = Environment()

        self.group_size = 3
        self.interval = 0.5

        self.workflow = SupportWorkflow(
            story_points=1, group_size=self.group_size)

        self.store = TaskStore(
            self.env, SDLCWorkflow.WorkflowState.DEVELOPMENT)

    def test_start_stop(self):

        self.workflow.start(env=self.env,
                            interval=0.5,
                            target=self.store)

        steps = 10
        self.assertEqual(0, len(self.store.items))
        self.env.run(until=steps)

        expected_count = ((steps/self.interval)-1) * self.group_size
        self.assertEqual(expected_count, len(self.store.items))

        self.workflow.stop()

        self.env.run(steps+20)

        self.assertEqual(expected_count, len(self.store.items))

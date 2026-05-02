import unittest

from simpy import Environment

from value_stream.resources import Resource
from value_stream import Task, WorkflowStateName


class TestResource(unittest.TestCase):
    def test_validation(self):
        resource = Resource(workflow_state=WorkflowStateName.DEVELOPMENT)
        task = Task(initial_value=2.0, story_points=1.0)
        env = Environment()

        with self.assertRaises(NotImplementedError):
            resource.do_work(env=env, tasks=[task])

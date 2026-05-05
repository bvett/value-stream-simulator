import unittest

from simpy import Environment, Store

from value_stream.resources import Resource
from value_stream import EventStatus, Task, WorkflowStateName


class TestResource(unittest.TestCase):
    def setUp(self):
        self.task = Task(initial_value=2.0, story_points=1.0)
        self.env = Environment()
        self.target = Store(self.env)
        self.target_for_failures = Store(self.env)

    def test_validation(self):
        resource = Resource(workflow_state=WorkflowStateName.DEVELOPMENT)

        with self.assertRaises(NotImplementedError):
            resource.do_work(env=self.env, tasks=[self.task])

    def run_and_assert(self, resource: Resource, expected_status: EventStatus):

        self.env.process(resource.operate(
            env=self.env, tasks=[self.task], target=self.target,
            target_upon_failure=self.target_for_failures))
        self.env.run()

        self.assertEqual(self.env.now, 1.0)
        self.assertEqual(len(self.task.history.events), 2)
        self.assertEqual(
            self.task.history.events[1].status, expected_status)

    def test_default_result(self):
        resource = DefaultQAResource()
        self.run_and_assert(resource, EventStatus.SUCCESS)
        self.assertEqual(len(self.target.items), 1)
        self.assertEqual(len(self.target_for_failures.items), 0)

    def test_successful_result(self):
        resource = SuccessQAResource()
        self.run_and_assert(resource, EventStatus.SUCCESS)
        self.assertEqual(len(self.target.items), 1)
        self.assertEqual(len(self.target_for_failures.items), 0)

    def test_failed_resource(self):
        resource = FailureQAResource()
        self.run_and_assert(resource, EventStatus.FAILURE)
        self.assertEqual(len(self.target.items), 0)
        self.assertEqual(len(self.target_for_failures.items), 1)


class DefaultQAResource(Resource):
    def __init__(self):
        super().__init__(WorkflowStateName.QA_TESTING)

    def do_work(self, env: Environment, tasks: list[Task]):
        work = env.timeout(tasks[0].story_points)
        yield work
        return work.value


class SuccessQAResource(Resource):
    def __init__(self):
        super().__init__(WorkflowStateName.QA_TESTING)

    def do_work(self, env: Environment, tasks: list[Task]):
        work = env.timeout(tasks[0].story_points, value={
                           'result': EventStatus.SUCCESS})
        yield work
        return work.value


class FailureQAResource(Resource):
    def __init__(self):
        super().__init__(WorkflowStateName.QA_TESTING)

    def do_work(self, env: Environment, tasks: list[Task]):
        work = env.timeout(tasks[0].story_points, value={
                           'result': EventStatus.FAILURE})
        yield work
        return work.value

import unittest

from simpy import Environment, Store


from value_stream.core import EventStatus
from value_stream.task import Task, TaskType
from value_stream.workflow import DefaultRouter, StatusRouter, TypeRouter


class TestTaskRouter(unittest.TestCase):
    def setUp(self):

        self.support_task = Task(
            initial_value=1, story_points=1, task_type=TaskType.SUPPORT)
        self.development_task = Task(
            initial_value=1, story_points=1, task_type=TaskType.DEVELOPMENT)

        self.env = Environment()

        self.successful_queue = Store(self.env)
        self.failure_queue = Store(self.env)

        self.development_queue = Store(self.env)
        self.support_queue = Store(self.env)

    def test_default_router(self):

        router = DefaultRouter(route=self.successful_queue)

        router.route(self.development_task)
        router.route(self.development_task)

        self.assertEqual(2, len(self.successful_queue.items))

    def test_status_router(self):

        router = StatusRouter(
            on_success=self.successful_queue, on_failure=self.failure_queue)

        router.route(self.development_task, EventStatus.SUCCESS)
        self.assertEqual(1, len(self.successful_queue.items))
        self.assertEqual(0, len(self.failure_queue.items))

        router.route(self.development_task, EventStatus.FAILURE)
        self.assertEqual(1, len(self.successful_queue.items))
        self.assertEqual(1, len(self.failure_queue.items))

    def test_type_router(self):

        router = TypeRouter(on_support=self.support_queue,
                            on_development=self.development_queue)

        router.route(self.development_task, EventStatus.SUCCESS)
        router.route(self.development_task, EventStatus.FAILURE)

        self.assertEqual(2, len(self.development_queue.items))
        self.assertEqual(0, len(self.support_queue.items))

        router.route(self.support_task, EventStatus.SUCCESS)
        router.route(self.support_task, EventStatus.FAILURE)

        self.assertEqual(2, len(self.development_queue.items))
        self.assertEqual(2, len(self.support_queue.items))

        router.route(self.development_task)
        self.assertEqual(3, len(self.development_queue.items))

    def test_chained(self):
        # combine support and status, assert length of resulting queues

        status_router = StatusRouter(
            on_success=self.successful_queue, on_failure=self.failure_queue)

        type_router = TypeRouter(
            on_support=self.support_queue, on_development=status_router)

        type_router.route(self.support_task, EventStatus.SUCCESS)
        type_router.route(self.support_task, EventStatus.FAILURE)
        type_router.route(self.support_task)

        self.assertEqual(3, len(self.support_queue.items))
        self.assertEqual(0, len(self.development_queue.items))
        self.assertEqual(0, len(self.successful_queue.items))
        self.assertEqual(0, len(self.failure_queue.items))

        type_router.route(self.development_task, EventStatus.SUCCESS)
        type_router.route(self.development_task, EventStatus.FAILURE)
        type_router.route(self.development_task)

        self.assertEqual(3, len(self.support_queue.items))
        self.assertEqual(0, len(self.development_queue.items))
        self.assertEqual(1, len(self.successful_queue.items))
        self.assertEqual(2, len(self.failure_queue.items))

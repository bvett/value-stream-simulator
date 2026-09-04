import unittest

from simpy import Environment, Store


from value_stream.core import WorkflowStateName
from value_stream.resources import QATester, Resource, ResourceTracker
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.task import Task, TaskRouterBase, DefaultRouter
from value_stream.workflow import ResourceOperator


class TestQAManager(unittest.TestCase):

    def setUp(self):
        self.env = Environment()
        self.tracker = ResourceTracker(self.env)

        self.complexities = [1.0, 3.0]
        self.tasks: list[Task] = []

        for c in self.complexities:
            self.tasks.append(Task(initial_value=1.0, story_points=c))

        self.policy = DefaultSimulationPolicy()

        self.workflow_state = WorkflowStateName.QA_TESTING

    def _process_task(self, task: Task, m: ResourceOperator, task_router: TaskRouterBase,  workflow_state: WorkflowStateName):
        e = m.request(self.workflow_state)

        operator: Resource = yield e

        yield self.env.process(operator.operate(self.env, [task], task_router=task_router, workflow_state=workflow_state, policy=self.policy, tracker=self.tracker))
        yield m.release(operator)

    def _test_loop(self, m: ResourceOperator, t: TaskRouterBase):
        for task in self.tasks:
            self.env.process(self._process_task(
                task, m, task_router=t, workflow_state=self.workflow_state))

    def test_serial(self):

        # 1 QA Tester, 2 Tasks
        manager = ResourceOperator(
            self.env, tracker=self.tracker, resources=QATester.create_pool(limit=1), policy=self.policy)
        target = Store(self.env)
        task_router = DefaultRouter(target)

        self._test_loop(manager, task_router)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, sum(self.complexities)*0.1)

    def test_parallel(self):
        # 2 QA Testers, 2 tasks

        manager = ResourceOperator(
            self.env, tracker=self.tracker, resources=QATester.create_pool(limit=2), policy=self.policy)
        target = Store(self.env)
        task_router = DefaultRouter(target)

        self._test_loop(manager, task_router)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, max(self.complexities)*0.1)

    def test_parallel_2(self):
        # unlimited QA Testers, 2 tasks
        manager = ResourceOperator(
            self.env, tracker=self.tracker, resources=QATester.create_pool(), policy=self.policy)
        target = Store(self.env)
        task_router = DefaultRouter(target)

        self._test_loop(manager, task_router)
        self.env.run()

        self.assertEqual(len(target.items), len(self.tasks))
        self.assertEqual(self.env.now, max(self.complexities)*0.1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            next(QATester.create_pool(limit=-1))

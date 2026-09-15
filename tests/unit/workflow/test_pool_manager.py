from typing import Any, Generator, Optional
import unittest

from simpy import Environment, Timeout, Interrupt
from simpy.events import AnyOf
from simpy.resources.store import StoreGet

from value_stream.factory import TaskFactory
from value_stream.task import Task, TaskState, SupportTask, TaskType
from value_stream.resources import Resource, ResourceTracker, Toolchain
from value_stream.workflow import AssignmentStrategy, WorkflowPolicy, PoolManager

# pylint: disable=W0212


class TestPoolManager(unittest.TestCase):

    class PolicyRandom(WorkflowPolicy):
        def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
            return AssignmentStrategy.RANDOM

    class PolicyCyclic(WorkflowPolicy):
        def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
            return AssignmentStrategy.CYCLIC

    class PolicyOwner(WorkflowPolicy):
        def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
            return AssignmentStrategy.OWNER

    class PolicyNext(WorkflowPolicy):
        def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
            return AssignmentStrategy.NEXT_AVAILABLE

    class DynamicPolicy(WorkflowPolicy):
        def __init__(self, strategy: AssignmentStrategy):
            self.strategy = strategy

        def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
            return self.strategy

    # emulate the default simulation policy
    class DefaultPolicy(WorkflowPolicy):
        def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
            if tasks:
                task = tasks[0]

                if (task.task_type == TaskType.DEVELOPMENT) and (task.is_rework is True):
                    return AssignmentStrategy.OWNER

                if task.task_type == TaskType.SUPPORT:
                    return AssignmentStrategy.RANDOM

            return AssignmentStrategy.NEXT_AVAILABLE

    class SimpleResource(Resource):
        def do_work(self, env: Environment, tasks: list[Task]) -> Generator[Timeout, Any, None]:
            yield env.timeout(1)

    class TestState(TaskState):
        DEFAULT = 'default'

    def setUp(self):
        self.env = Environment()

        self.tracker = ResourceTracker(self.env)

        num_resources = 5
        self.resources: list[Resource] = []

        for _ in range(num_resources):
            self.resources.append(self.SimpleResource())

        self.state = self.TestState.DEFAULT

        num_tasks = 10
        self.tasks: list[Task] = TaskFactory(
            story_points=1, initial_value=1).create(num_tasks)

        self.support_tasks: list[Task] = TaskFactory(
            cls=SupportTask, story_points=1).create(num_tasks)

    def run_scenario(self, manager: PoolManager, task: Task, resource_allocation: dict[Resource, int]):
        r = manager.request(self.state, [task])

        self.assertTrue(isinstance(r, Resource)
                        or isinstance(r, StoreGet))

        resource: Optional[Resource] = None

        if isinstance(r, StoreGet):
            resource = yield r

            if resource is None:
                raise ValueError(
                    "unexpected None for resource during test execution")

            yield self.env.process(resource.do_work(self.env, [task]))
            yield manager.release(resource)

        if isinstance(r, Resource):
            resource = r
            yield self.env.process(r.do_work(self.env, [task]))

        if (resource is not None):
            if (resource not in resource_allocation):
                resource_allocation[resource] = 1
            else:
                resource_allocation[resource] += 1

    def test_cyclic(self):

        manager = PoolManager(
            env=self.env,
            resources=iter(self.resources),
            policy=self.PolicyCyclic(),
            tracker=self.tracker)

        resource_allocation: dict[Resource, int] = {}

        for task in self.tasks:
            self.env.process(self.run_scenario(
                task=task, manager=manager, resource_allocation=resource_allocation))

        self.env.run()

        self.assertEqual(len(self.resources), len(resource_allocation.keys()))
        for _, v in resource_allocation.items():
            self.assertEqual(2, v)

        self.assertEqual(len(self.resources), len(
            manager._registered_resources))

        allocated = 0
        for metadata in self.tracker.data:
            if metadata.state == self.state:
                allocated += metadata.allocated

        self.assertEqual(len(self.resources), allocated)

    def create_batches(self, batch_size: int, num_batches: int, manager: PoolManager) -> list[list[Resource]]:
        batches: list[list[Resource]] = []
        for _ in range(num_batches):
            resources: list[Resource] = []

            for _ in range(batch_size):
                resource: Resource = manager.request(
                    self.state, self.tasks)  # type:ignore
                self.assertTrue(isinstance(resource, Resource))
                resources.append(resource)

            batches.append(resources.copy())

        return batches

    def test_cyclic_ordering(self):
        manager = PoolManager(
            env=self.env,
            resources=iter(self.resources),
            policy=self.PolicyCyclic(),
            tracker=self.tracker)

        num_batches = 3
        batches = self.create_batches(
            batch_size=15, num_batches=num_batches, manager=manager)

        for i in range(num_batches-1):
            self.assertEqual(batches[i], batches[i+1])

    def test_next_available(self):
        """validates resources are returned in the same order across different sequences of requests"""

        # request,request, release, release...
        manager = PoolManager(
            env=self.env,
            resources=iter(self.resources),
            policy=self.PolicyNext(),
            tracker=self.tracker)

        resources: list[Resource] = []

        def make_requests(count: int, result: Optional[list[Resource]]) -> Generator[StoreGet, Any, None]:

            for _ in range(count):
                request = manager.request(self.state, self.tasks)
                self.assertTrue(isinstance(request, StoreGet))
                try:
                    resource = yield request  # type:ignore
                    if result is not None:
                        result.append(resource)
                except Interrupt:
                    request.cancel()  # type:ignore

        self.env.process(make_requests(len(self.resources), resources))

        self.env.run()

        self.assertEqual(len(self.resources), len(resources))
        self.assertEqual(0, len(manager._resource_pool.items))

        # try to request more than what's available, ensure waiting happens

        empty_list: list[Resource] = []  # should remain empty
        p = self.env.process(make_requests(1, empty_list))
        timeout = self.env.timeout(3)
        self.env.run(AnyOf(self.env, [timeout, p]))

        self.assertTrue(timeout.triggered)
        self.assertFalse(p.triggered)
        self.assertTrue(p.is_alive)
        self.assertFalse(p.defused)
        p.interrupt()
        self.assertEqual(0, len(empty_list))

        def release_resources(resources: list[Resource]):
            for resource in resources:
                yield manager.release(resource)

        self.env.process(release_resources(resources))
        self.env.run()

        self.assertEqual(len(self.resources), len(
            manager._resource_pool.items))

    def test_random(self):
        manager = PoolManager(
            env=self.env,
            resources=iter(self.resources),
            policy=self.PolicyRandom(),
            tracker=self.tracker)

        resource_allocation: dict[Resource, int] = {}

        for task in self.tasks:
            self.env.process(self.run_scenario(
                task=task, manager=manager, resource_allocation=resource_allocation))

        self.env.run()

        # since the allocations are random, it's impossible to assert anything about the distribution of allocations.
        # just ensure they total.

        total_allocations: int = 0
        for _, v in resource_allocation.items():
            total_allocations += v

        self.assertEqual(len(self.tasks), total_allocations)
        self.assertIsNotNone(manager._resources_as_list)
        self.assertEqual(len(self.resources), len(
            manager._resources_as_list))  # type: ignore

    def test_random_ordering(self):
        manager = PoolManager(
            env=self.env,
            resources=iter(self.resources),
            policy=self.PolicyRandom(),
            tracker=self.tracker)

        # Technically, there is a nonzero probability of generating 5 identical sequences of 20
        num_batches = 5
        batches = self.create_batches(
            batch_size=20, num_batches=num_batches, manager=manager)

        for i in range(num_batches-1):
            self.assertNotEqual(batches[i], batches[i+1])

    def test_owner(self):
        #
        policy = self.DynamicPolicy(strategy=AssignmentStrategy.NEXT_AVAILABLE)

        manager = PoolManager(
            env=self.env,
            resources=iter(self.resources),
            policy=policy,
            tracker=self.tracker)

        # First, establish ownership by choosing the next available resource
        task_group_1 = TaskFactory(
            initial_value=1, story_points=1).create(5, self.env)

        task_group_2 = TaskFactory(
            initial_value=1, story_points=1).create(5, self.env)

        def request(tasks: list[Task]) -> Generator[StoreGet, Any, Any]:

            request = manager.request(self.state, tasks)
            self.assertTrue(isinstance(request, StoreGet))

            resource = yield request  # type:ignore

            return resource

        def release(resource: Resource):
            yield manager.release(resource)

        p1 = self.env.process(request(task_group_1))
        p2 = self.env.process(request(task_group_2))

        self.env.run()

        resource_1: Resource = p1.value  # type:ignore
        resource_2: Resource = p2.value  # type:ignore

        self.env.process(release(resource_1))
        self.env.process(release(resource_2))

        self.env.run()

        # Next, validate that the chosen resource continues to be assigned to the same task

        policy.strategy = AssignmentStrategy.OWNER

        r1: Resource = manager.request(self.state, task_group_1)  # type:ignore
        r2: Resource = manager.request(self.state, task_group_2)  # type:ignore

        self.assertEqual(r1, resource_1)
        self.assertEqual(r2, resource_2)
        self.assertNotEqual(r1, r2)

        # validate there's an exception when the owner cannot be identified.

        unowned_tasks = TaskFactory(story_points=1, initial_value=1).create(3)
        with self.assertRaises(ValueError):
            manager.request(self.state, unowned_tasks)

    def test_random_with_unlimited_pool(self):
        # attempt to use with an unlimited resource pool

        unlimited_pool = Toolchain.create_pool(
            limit=None,
            deployment_duration=1,
            failure_rate=1)

        manager = PoolManager(
            env=self.env,
            resources=unlimited_pool,
            policy=self.PolicyRandom(),
            tracker=self.tracker)

        iterations = 10
        toolchains = []
        for _ in range(iterations):
            toolchains.append(manager.request(self.state, self.tasks))

        for i in range(iterations-1):
            self.assertNotEqual(toolchains[i], toolchains[i+1])

    def test_multi_policy(self):
        # check that resources iterator isn't at the end when _resources_as_list is populated.

        simple_resource = self.SimpleResource()

        manager = PoolManager(
            env=self.env,
            resources=iter([simple_resource]),
            policy=self.DefaultPolicy(),
            tracker=self.tracker)

        regular_task = Task(initial_value=1, story_points=1)
        support_task = SupportTask(story_points=1)

        def request(tasks: list[Task]) -> Generator[StoreGet, Any, Any]:

            request = manager.request(self.state, tasks)
            if isinstance(request, StoreGet):
                resource = yield request  # type:ignore
            else:
                resource = request

            return resource

        p1 = self.env.process(request([regular_task]))

        self.env.run()

        r1: Resource = p1.value  # type:ignore
        r2: Resource = manager.request(
            self.state, [support_task])  # type:ignore

        self.assertEqual(simple_resource, r1)
        self.assertEqual(simple_resource, r2)

import itertools
import random
from typing import Iterator, Optional
from uuid import UUID
from simpy import Environment, Store
from simpy.resources.store import StoreGet

from value_stream.core import WorkflowStateName
from value_stream.policy import AssignmentStrategy
from value_stream.resources import Resource, ResourceTracker
from value_stream.task import Task

from .workflow_policy import WorkflowPolicy


class PoolManager:
    def __init__(self, env: Environment, resources: Iterator[Resource], policy: WorkflowPolicy, tracker: Optional[ResourceTracker] = None):
        self.resources = resources
        self.policy = policy
        self._tracker = tracker

        self._env = env
        self._resource_pool = Store(self._env)

        self._task_owners: dict[UUID, Resource] = {}

        self._all_resources: list[Resource] = []
        self._cyclic_support_delegator = None
        self._random_support_delegator = None

    def _update_delegators(self, r: list[Resource]):

        def gen(resources: list[Resource]):
            while True:
                yield random.choice(resources)

        self._cyclic_support_delegator = itertools.cycle(r)
        self._random_support_delegator = gen(r)

    def request(self, workflow_state: WorkflowStateName, tasks: list[Task]):

        strategy = self.policy.support_assignment_strategy(tasks)

        match strategy:
            case AssignmentStrategy.CYCLIC:
                if self._cyclic_support_delegator is not None:
                    return next(self._cyclic_support_delegator)
            case AssignmentStrategy.RANDOM:
                if self._random_support_delegator is not None:
                    return next(self._random_support_delegator)
            case AssignmentStrategy.OWNER:
                task = tasks[0]

                if not task.task_id in self._task_owners:
                    pass

                owner: Resource = self._task_owners[task.task_id]
                return owner

        # default to AssignmentStrategy.NEXT_AVAILABLE:

        if len(self._resource_pool.items) == 0:

            new_item = next(self.resources, None)

            if new_item is not None:
                new_item.idle_t = self._env.now
                self._resource_pool.put(new_item)
                self._all_resources.append(new_item)
                self._update_delegators(self._all_resources)

                if self._tracker is not None:
                    self._tracker.register(workflow_state)

        result = self._resource_pool.get()

        def record_owner(event: StoreGet):
            resource: Optional[Resource] = event.value

            if resource is not None:
                for task in tasks:
                    self._task_owners[task.task_id] = resource

        result.callbacks = [record_owner]
        return result

    def release(self, resource: Resource):
        resource.idle_t = self._env.now
        return self._resource_pool.put(resource)

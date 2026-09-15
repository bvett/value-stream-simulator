import itertools
import random
from typing import Iterator, Optional
from uuid import UUID
from simpy import Environment, Store
from simpy.resources.store import StoreGet

from value_stream.task import TaskState
from value_stream.resources import Resource, ResourceTracker, ResourcePool
from value_stream.task import Task

from .assignment_strategy import AssignmentStrategy
from .workflow_policy import WorkflowPolicy


class PoolManager:
    def __init__(self, env: Environment, resources: Iterator[Resource], policy: WorkflowPolicy, tracker: Optional[ResourceTracker] = None):

        self.policy = policy
        self._tracker = tracker

        self._env = env
        self._resource_pool = Store(self._env)

        self._task_owners: dict[UUID, Resource] = {}

        # used for enabling a random item to be chosen from an iterator
        self._resources_as_list: Optional[list[Resource]] = None

        self.resources = resources

        self._registered_resources: set[Resource] = set()

        self._cyclic_support_delegator = itertools.cycle(self.resources)

    def request(self, workflow_state: TaskState, tasks: list[Task]):

        strategy = self.policy.support_assignment_strategy(tasks)

        match strategy:
            case AssignmentStrategy.CYCLIC:
                resource = next(self._cyclic_support_delegator)
                if (resource not in self._registered_resources) and (self._tracker is not None):
                    self._tracker.register(workflow_state)
                    self._registered_resources.add(resource)

                return resource

            case AssignmentStrategy.RANDOM:
                # realistically, if resources are unlimited, then just get next
                if isinstance(self.resources, ResourcePool) and (self.resources.limit is None):
                    resource = next(self.resources)
                else:
                    if self._resources_as_list is None:
                        self._resources_as_list = list(
                            self._registered_resources)
                        self._resources_as_list.extend(list(self.resources))
                    resource = random.choice(self._resources_as_list)

                if (resource not in self._registered_resources) and (self._tracker is not None):
                    self._tracker.register(workflow_state)
                    self._registered_resources.add(resource)

                return resource

            case AssignmentStrategy.OWNER:
                task = tasks[0]

                if not task.task_id in self._task_owners:
                    raise ValueError(
                        f"Unable to identify task owner for task_id: {task.task_id}")

                owner: Resource = self._task_owners[task.task_id]
                return owner

        # default to AssignmentStrategy.NEXT_AVAILABLE:

        if len(self._resource_pool.items) == 0:

            resource = next(self.resources, None)

            if resource is not None:
                resource.idle_t = self._env.now
                self._resource_pool.put(resource)

                if (resource not in self._registered_resources) and (self._tracker is not None):
                    self._tracker.register(workflow_state)
                    self._registered_resources.add(resource)

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

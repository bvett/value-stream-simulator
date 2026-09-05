from typing import Iterator, Optional
from simpy import Environment, Store

from value_stream.core import WorkflowStateName
from value_stream.resources import Resource, ResourceTracker, ResourcePolicy


class PoolManager:
    def __init__(self, env: Environment, resources: Iterator[Resource], policy: ResourcePolicy, tracker: Optional[ResourceTracker] = None):
        self.resources = resources
        self.policy = policy
        self._tracker = tracker

        self._env = env
        self._resource_pool = Store(self._env)

    def request(self, workflow_state: WorkflowStateName, ):

        if len(self._resource_pool.items) == 0:

            new_item = next(self.resources, None)

            if new_item is not None:
                new_item.idle_t = self._env.now
                self._resource_pool.put(new_item)
                if self._tracker is not None:
                    self._tracker.register(workflow_state)

        return self._resource_pool.get()

    def release(self, resource: Resource):
        # do we release resources that were immediately assigned?
        resource.idle_t = self._env.now
        return self._resource_pool.put(resource)

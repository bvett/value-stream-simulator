from typing import Collection
from simpy import Environment, Store

from ..resources import Resource
from .manager import Manager


class DeveloperManager(Manager):
    """Manages a pool of developers"""

    def __init__(self, env: Environment, resources: Collection[Resource]):
        super().__init__(env, cadence=0)

        self.resource_pool = Store(self.env)

        self.resource_generator = iter(resources)

    def request(self):

        new_item = next(self.resource_generator, None)

        if new_item is None:
            return self.resource_pool.get()

        return self.env.event().succeed(new_item)

    def release(self, operator: Resource):
        return self.resource_pool.put(operator)

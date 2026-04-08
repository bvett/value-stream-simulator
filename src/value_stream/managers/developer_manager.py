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
        if len(self.resource_pool.items) == 0:

            new_item = next(self.resource_generator, None)

            if new_item is not None:
                self.resource_pool.put(new_item)

        return self.resource_pool.get()

    def release(self, operator: Resource):
        return self.resource_pool.put(operator)

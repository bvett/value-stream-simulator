from simpy import Environment, Store

from ..resources import Resource, Developer
from .manager import Manager


class DeveloperManager(Manager):
    """Manages a pool of developers"""

    def __init__(self, env: Environment, developers: list[Developer]):
        super().__init__(env, cadence=0)

        self.developers = Store(self.env, len(developers))

        for developer in developers:
            self.developers.put(developer)

    def request(self):
        return self.developers.get()

    def release(self, operator: Resource):
        return self.developers.put(operator)

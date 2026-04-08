from typing import Iterable
from simpy import Environment

from ..resources import Resource
from .manager import Manager


class DeveloperManager(Manager):
    """Manages a pool of developers"""

    def __init__(self, env: Environment, resources: Iterable[Resource]):
        super().__init__(env, resources, cadence=0)

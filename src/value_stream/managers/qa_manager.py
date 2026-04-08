from typing import Iterable
from simpy import Environment
from .manager import Manager
from ..resources import Resource


class QAManager(Manager):
    def __init__(self, env: Environment, resources: Iterable[Resource]):
        super().__init__(env, resources, cadence=0)

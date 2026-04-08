from typing import Iterable
from simpy import Environment

from ..resources import Resource
from .manager import Manager


class ToolchainManager(Manager):
    """Simulates concurrency of CI/CD automation.

    In some enterprises, deployment infrastructure is not completely elastic,
    requiring deployment requests to be queued if server resources are
    unavailable.

    """

    def __init__(self, env: Environment, resources: Iterable[Resource], deployment_cadence: int):
        super().__init__(env, resources, cadence=deployment_cadence)

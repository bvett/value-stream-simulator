from simpy import Environment, Store

from ..resources import Resource, Toolchain
from .manager import Manager


class ToolchainManager(Manager):
    """Simulates concurrency of CI/CD automation.

    In some enterprises, deployment infrastructure is not completely elastic,
    requiring deployment requests to be queued if server resources are
    unavailable.

    """

    def __init__(self, env: Environment, deployment_duration: float, deployment_cadence: int, concurrency: int = 1):
        super().__init__(env, deployment_cadence)

        if deployment_duration < 0:
            raise ValueError("deployment_duration must be >= 0")

        self.deployment_duration = deployment_duration

        if deployment_cadence < 0:
            raise ValueError("deployment_cadence must be >= 0")

        self.toolchain_opreators = Store(self.env, concurrency)

        for _ in range(concurrency):
            self.toolchain_opreators.put(
                Toolchain(self.deployment_duration))

    def request(self):
        return self.toolchain_opreators.get()

    def release(self, operator: Resource):
        return self.toolchain_opreators.put(operator)

from simpy import Environment
from ..resources import Resource, PooledResource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Toolchain(Resource, PooledResource):
    """Simulates actions performed on tasks by SDLC tooling"""

    def __init__(self, deployment_duration: float):
        super().__init__(WorkflowStateName.DEPLOYMENT)

        if deployment_duration < 0:
            raise ValueError("deployment_duration must be >= 0")

        self.deployment_duration = deployment_duration

    def do_work(self, env: Environment, tasks: list[Task]):
        yield env.timeout(self.deployment_duration)

import random

from simpy import Environment
from ..event_status import EventStatus
from ..resources import Resource, PooledResource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Toolchain(Resource, PooledResource):
    """Simulates actions performed on tasks by SDLC tooling"""

    def __init__(self, deployment_duration: float,
                 failure_rate: float = 0.0):
        super().__init__(WorkflowStateName.DEPLOYMENT)

        self.failure_rate = failure_rate

        if deployment_duration < 0:
            raise ValueError("deployment_duration must be >= 0")

        if failure_rate < 0 or failure_rate > 1:
            raise ValueError("failure_rate must be between 0 and 1, inclusive")

        self.deployment_duration = deployment_duration

    def do_work(self, env: Environment, tasks: list[Task]):

        if random.random() < self.failure_rate:
            result = EventStatus.FAILURE
        else:
            result = EventStatus.SUCCESS

        work = env.timeout(self.deployment_duration, value={'result': result})

        yield work

        return work.value

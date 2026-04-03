from ..resources import Resource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Toolchain(Resource):
    """Simulates actions performed on tasks by SDLC tooling"""

    def __init__(self, deployment_duration: float):
        super().__init__(WorkflowStateName.DEPLOYMENT)

        if deployment_duration < 0:
            raise ValueError("deployment_duration must be >= 0")

        self.deployment_duration = deployment_duration

    def effort(self, tasks: list[Task]) -> float:
        return self.deployment_duration

    @classmethod
    def create(cls, deployment_duration: float, limit: int | None = None):

        if limit is None:
            while True:
                yield Toolchain(deployment_duration=deployment_duration)

        if limit <= 0:
            raise ValueError("limit must be >0")

        for _ in range(limit):
            yield Toolchain(deployment_duration=deployment_duration)

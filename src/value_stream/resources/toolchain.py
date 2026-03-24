from ..resources import Resource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Toolchain(Resource):
    """Simulates actions performed on tasks by SDLC tooling"""

    def __init__(self, deployment_duration: float):
        super().__init__(WorkflowStateName.DEPLOYMENT)

        self.deployment_duration = deployment_duration

    def effort(self, tasks: list[Task]) -> float:
        return self.deployment_duration

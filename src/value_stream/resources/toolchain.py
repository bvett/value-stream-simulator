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


class ToolchainPool():
    def __init__(self, limit: int | None = None, **kwargs):
        if limit is not None and limit <= 0:
            raise ValueError("limit must be >0")

        self.limit = limit
        self.kwargs = kwargs

    def create(self):
        if self.limit is None:
            while True:
                yield Toolchain(**self.kwargs)

        for _ in range(self.limit):
            yield Toolchain(**self.kwargs)

    def __iter__(self):
        return iter(self.create())

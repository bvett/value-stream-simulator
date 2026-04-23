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

        self._i = 0

    def __next__(self):
        if self.limit is None:
            return Toolchain(**self.kwargs)

        if self._i < self.limit:
            self._i += 1
            return Toolchain(**self.kwargs)

        raise StopIteration

    def __iter__(self):
        self._i = 0
        return self

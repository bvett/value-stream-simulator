from .resource import Resource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Developer(Resource):
    """Simulates actions perform on a task by a software developer"""

    def __init__(self, efficiency: float = 1.0, name: str | None = None):
        super().__init__(WorkflowStateName.DEVELOPMENT)

        if efficiency <= 0:
            raise ValueError("efficiency must be > 0")

        self.name: str = name if name else ""
        self.efficiency: float = efficiency

    def effort(self, tasks: list[Task]) -> float:
        return sum([task.complexity / self.efficiency for task in tasks])

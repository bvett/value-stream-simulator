from .resource import Resource
from .resource_pool import PooledResource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class QATester(Resource, PooledResource):
    def __init__(self, time_cost: float = 0.1):
        super().__init__(workflow_state=WorkflowStateName.QA_TESTING)
        self.time_cost = time_cost

    def effort(self, tasks: list[Task]) -> float:
        return sum(task.story_points * self.time_cost for task in tasks)

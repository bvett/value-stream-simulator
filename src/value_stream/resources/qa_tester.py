import random
from simpy import Environment
from ..event_status import EventStatus
from .resource import Resource
from .resource_pool import PooledResource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class QATester(Resource, PooledResource):
    def __init__(self, time_cost: float = 0.1, failure_rate: float = 0.0):
        super().__init__(workflow_state=WorkflowStateName.QA_TESTING)

        if failure_rate < 0 or failure_rate > 1:
            raise ValueError("failure_rate must be between 0 and 1, inclusive")

        self.time_cost = time_cost
        self.failure_rate = failure_rate

    def do_work(self, env: Environment, tasks: list[Task]):
        effort = sum(task.story_points * self.time_cost for task in tasks)

        if random.random() < self.failure_rate:
            result = EventStatus.FAILURE
        else:
            result = EventStatus.SUCCESS

        work = env.timeout(effort, value={'result': result})

        yield work

        return work.value

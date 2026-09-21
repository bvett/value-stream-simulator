import random
from pydantic import FiniteFloat, Field
from simpy import Environment

from value_stream.task import EventStatus, Task

from .resource import Resource
from .resource_pool import PooledResource


class QATester(Resource, PooledResource):

    time_cost: FiniteFloat = Field(default=0.1)
    failure_rate: FiniteFloat = Field(default=0.0, ge=0, le=1)
    failure_cost: FiniteFloat = Field(default=0.0, ge=0, le=1)

    def do_work(self, env: Environment, tasks: list[Task]):
        effort = sum(task.story_points * self.time_cost for task in tasks)

        if random.random() < self.failure_rate:
            result = EventStatus.FAILURE
        else:
            result = EventStatus.SUCCESS

        work = env.timeout(effort, value={'result': result})

        yield work

        # Cost of remediation is a perceentage of original effort
        if result == EventStatus.FAILURE:
            for task in tasks:
                remediation_work = task.story_points * self.failure_cost
                task.do_work(-remediation_work)

        return work.value

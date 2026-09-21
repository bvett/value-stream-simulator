import random

from pydantic import FiniteFloat, Field
from simpy import Environment

from value_stream.task import EventStatus, Task

from .resource_pool import PooledResource
from .resource import Resource


class Toolchain(Resource, PooledResource):
    """Simulates actions performed on tasks by SDLC tooling"""

    deployment_duration: FiniteFloat = Field(ge=0)
    failure_rate: FiniteFloat = Field(default=0, ge=0, le=1)

    def do_work(self, env: Environment, tasks: list[Task]):

        if random.random() < self.failure_rate:
            result = EventStatus.FAILURE
        else:
            result = EventStatus.SUCCESS

        work = env.timeout(self.deployment_duration, value={'result': result})

        yield work

        return work.value

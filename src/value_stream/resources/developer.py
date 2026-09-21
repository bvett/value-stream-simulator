from typing import Any, Generator

from pydantic import Field, FiniteFloat
from simpy import Environment, Interrupt, Timeout

from value_stream.task import EventStatus, Task

from .resource import Resource


class Developer(Resource):
    """Simulates actions perform on a task by a software developer"""

    efficiency: FiniteFloat = Field(default=1.0, gt=0)
    name: str = ""

    def effort(self, tasks: list[Task]) -> float:
        return sum([task.remaining_work() / self.efficiency for task in tasks])

    def do_work(self, env: Environment, tasks: list[Task]) -> Generator[Timeout, Any, None]:
        start = env.now

        try:
            yield env.timeout(self.effort(tasks), value={'result': EventStatus.SUCCESS})

        except Interrupt:
            applied_story_points = (env.now - start) * self.efficiency
            for task in tasks:
                applied_story_points = task.do_work(applied_story_points)

            raise

        applied_story_points = (env.now - start) * self.efficiency

        for task in tasks:
            applied_story_points = task.do_work(applied_story_points)

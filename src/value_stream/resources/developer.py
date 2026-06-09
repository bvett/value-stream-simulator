from simpy import Environment, Interrupt

from ..event_status import EventStatus
from .resource import Resource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Developer(Resource):
    """Simulates actions perform on a task by a software developer"""

    def __init__(self, efficiency: float = 1.0, name: str | None = None):
        super().__init__(WorkflowStateName.DEVELOPMENT, resource_id=name)

        if efficiency <= 0:
            raise ValueError("efficiency must be > 0")

        self.name: str = name if name else ""
        self.efficiency: float = efficiency

    def effort(self, tasks: list[Task]) -> float:
        return sum([task.remaining_work() / self.efficiency for task in tasks])

    def do_work(self, env: Environment, tasks: list[Task]):
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

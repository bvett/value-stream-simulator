from .model import Model
from .task import Task
from .task_event import TaskEvent


class SimulationResult:
    """Associates model metadata and task outcome with simulation events"""

    def __init__(self, model: Model, task: Task, events: list[TaskEvent]):
        self.model = model
        self.task = task
        self.events = events

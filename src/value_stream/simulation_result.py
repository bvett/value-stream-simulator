from .model import Model
from .simulation_metadata import SimulationMetadata
from .task import Task
from .task_event import TaskEvent


class SimulationResult:
    """Associates model metadata and task outcome with simulation events"""

    def __init__(self, model: Model, task: Task, events: list[TaskEvent]):
        self.model = model
        self.task = task
        self.events = events


class SummaryResult:

    def __init__(self, model: Model,
                 completion_time: float,
                 total_delivered_value: float,
                 loss: float) -> None:

        self.model = model
        self.completion_time = completion_time
        self.total_delivered_value = total_delivered_value
        self.loss = loss


class SimulationResultV2:

    def __init__(self, summary_result: SummaryResult, metadata: SimulationMetadata):
        self.summary_result = summary_result
        self.metadata: SimulationMetadata = metadata

from .event_status import EventStatus
from .model import Model
from .task import Task
from .task_event import TaskEvent
from .workflow_state_name import WorkflowStateName


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


class TimelineResult:

    def __init__(self, model: Model,
                 time: float,
                 duration: float,
                 workflow_state: WorkflowStateName,
                 value: float,
                 loss: float,
                 status: EventStatus):

        self.model = model
        self.time = time
        self.duration = duration
        self.workflow_state = workflow_state
        self.value = value
        self.loss = loss
        self.status = status


class SimulationResultV2:

    def __init__(self, summary_result: SummaryResult, detailed_result: list[TimelineResult] = []):
        self.summary_result = summary_result
        # self.detailed_result = detailed_result

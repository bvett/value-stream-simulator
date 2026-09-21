import copy
import uuid
from typing import Collection, Optional, Self

from pydantic import BaseModel, Field, PrivateAttr
from simpy import Environment

from .event_status import EventStatus
from .task_history import TaskHistory
from .task_type import TaskType
from .task_state import TaskState


class Task(BaseModel):
    """Represents a unit of delivery with depreciating value"""

    @classmethod
    def _generate_id(cls):
        return uuid.uuid4()

    @classmethod
    def start_epoch(cls, tasks: Collection[Self], env: Environment) -> list['Task']:
        return [t.reset(epoch_start_sim_t=env.now) for t in tasks]

    task_name : Optional[str] = Field(default=None)
    initial_value: float = Field(ge=0, frozen=True)
    story_points : float = Field(ge=0)
    creation_sim_t : float = Field(default = 0.0, ge=0, frozen=True)
    depreciation_rate : float = Field(default = 0.005, ge=0, le=1)
    task_type : TaskType = Field(default=TaskType.DEVELOPMENT)
    _history: TaskHistory = PrivateAttr(
        default_factory=lambda data: TaskHistory(epoch_start_sim_t=data['creation_sim_t']))
    _id : uuid.UUID = PrivateAttr(default_factory=uuid.uuid4)
    is_rework : bool = Field(default=False, init=False)



    @property
    def task_id(self) -> uuid.UUID:
        return self._id

    @property
    def history(self) -> TaskHistory:
        return self._history

    def value(self, epoch_t: Optional[float] = None) -> float:
        """Calculates the value of the task at a specified time

        Args:
            time (Optional[float], optional): Simulation time. Defaults to None.

        Returns:
            float: depreciated value of the task
        """
        if epoch_t is None:
            return self.initial_value

        sim_t = self.history.epoch.to_sim_time(epoch_t)

        return self.initial_value * ((1-self.depreciation_rate) ** (sim_t - self.creation_sim_t))

    def loss(self, from_epoch_t: float, to_epoch_t: float) -> float:
        """Returns percentage difference between initial value and delivered value, or 0 if undelivered."""

        starting_value = self.value(epoch_t=from_epoch_t)

        if (starting_value == 0) or (self.initial_value == 0):
            return 0

        ending_value = self.value(epoch_t=to_epoch_t)

        return (ending_value - starting_value) / self.initial_value

    def __str__(self) -> str:
        return self.task_name if self.task_name else ""

    def reset(self, epoch_start_sim_t: float = 0) -> "Task":
        """Returns a clone of the task except history"""

        result = Task(task_name = self.task_name,
                      initial_value=self.initial_value,
                      story_points = self.story_points,
                      creation_sim_t=epoch_start_sim_t,
                      depreciation_rate=self.depreciation_rate,
                      task_type=self.task_type)

        return result

    def remaining_work(self):
        return self.story_points - self.history.completed_story_points

    def do_work(self, story_points: float):

        # negative story points are allowed to represent regression
        remaining_work = self.remaining_work()

        if story_points <= remaining_work:
            self.history.completed_story_points += story_points

            if self.history.completed_story_points < 0:
                raise ValueError("completed_story_points cannot be negative")

            return 0.0

        self.history.completed_story_points = self.story_points
        return story_points - remaining_work

    def end(self, sim_t: float, event: Optional[TaskState] = None, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[uuid.UUID] = None):

        last_event = self.history.last_event()

        loss = 0 if last_event is None else self.loss(
            from_epoch_t=last_event.time, to_epoch_t=self.history.epoch.to_epoch_time(sim_t))

        self.history.end(sim_time=sim_t, event=event, status=status,
                         loss=loss, task_type=self.task_type, is_rework=self.is_rework)

    def start(self, sim_t: float, event: TaskState, resource_id: Optional[uuid.UUID] = None):
        self.history.start(sim_time=sim_t, event=event,
                           task_type=self.task_type, is_rework=self.is_rework, resource_id=resource_id)

    def resume(self, event: TaskState):
        self.history.resume(event=event)

    def terminate(self, sim_t: float, event: TaskState, status: EventStatus = EventStatus.SUCCESS, resource_id: Optional[uuid.UUID] = None):
        self.history.terminate(sim_time=sim_t, event=event, status=status,
                               task_type=self.task_type, is_rework=self.is_rework, resource_id=resource_id)

        delivered_epoch_t = self.history.epoch.to_epoch_time(sim_t)
        self.history.delivered_value = self.value(delivered_epoch_t)

    def as_rework(self) -> Self:
        self.is_rework = True
        return self

    def clear_rework(self) -> Self:
        self.is_rework = False
        return self


class SupportTask(Task):
    def __init__(self,
                 story_points: float,
                 task_name: Optional[str] = None,
                 creation_sim_t: float = 0.0):

        super().__init__(initial_value=0,
                         story_points=story_points,
                         depreciation_rate=0,
                         task_name=task_name,
                         creation_sim_t=creation_sim_t,
                         task_type=TaskType.SUPPORT)

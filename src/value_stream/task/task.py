import copy
import uuid
from enum import StrEnum
from typing import Optional, Self

from value_stream.core import EventStatus, WorkflowStateName

from .task_history import TaskHistory


class TaskType(StrEnum):
    """Task Categorization."""
    DEVELOPMENT = 'development'
    SUPPORT = 'support'


class Task:
    """Represents a unit of delivery with depreciating value"""

    @classmethod
    def _generate_id(cls):
        return uuid.uuid4()

    def __init__(self,
                 initial_value: float,
                 story_points: float,
                 depreciation_rate=0.005,
                 task_name: Optional[str] = None,
                 creation_time: float = 0.0,
                 task_type: TaskType = TaskType.DEVELOPMENT) -> None:
        """Creates a Task

        Args:
            initial_value (float): Relative value of the task

            story_points (float): Relative complexity of the task

            depreciation_rate (float, optional): Percentage of value 
              decrease per time unit. Defaults to 0.005.

            task_name (str): Public identifier. Optional.

            creation_time (float, optional): Relative time of task creation. Defaults to 0.0.

        """

        self.task_name = task_name

        if initial_value < 0:
            raise ValueError("initial_value must be >=0")

        self._initial_value = initial_value

        if story_points < 0:
            raise ValueError("story_points must be >= 0")

        self.story_points = story_points

        self.completed_story_points: float = 0

        if creation_time < 0:
            raise ValueError("creation_time must be >=0")

        self.creation_sim_t = creation_time

        if not 0 <= depreciation_rate <= 1:
            raise ValueError("depreciation_rate must >=0 and <=1")

        self.depreciation_rate = depreciation_rate

        self.task_type = task_type

        self.history = TaskHistory(epoch_start_t=self.creation_sim_t)

        self.delivered_loss: Optional[float] = None
        self.delivered_value: Optional[float] = None

        self._id = Task._generate_id()

    @property
    def task_id(self) -> uuid.UUID:
        return self._id

    def value(self, epoch_t: Optional[float] = None) -> float:
        """Calculates the value of the task at a specified time

        Args:
            time (Optional[float], optional): Simulation time. Defaults to None.

        Returns:
            float: depreciated value of the task
        """
        if epoch_t is None:
            return self._initial_value

        sim_t = self.history.epoch.to_sim_time(epoch_t)

        if sim_t < self.creation_sim_t:
            raise ValueError("time must be >= creation_t")

        return self._initial_value * ((1-self.depreciation_rate) ** (sim_t - self.creation_sim_t))

    def delivered_time(self):
        """Returns the time the task was successfully delivered, otherwise None"""
        last_event = self.history.last_event()

        if (last_event is not None) \
                and (last_event.status == EventStatus.SUCCESS) \
                and last_event.event_type == last_event.EventType.TERMINAL:

            return last_event.time

        return None

    # TODO: make agnostic of workflow states
    def _delivered_value(self) -> float:
        """Returns the depreciated value of the task at the time of delivery, or its initial value if undelivered.
        """

        delivered_epoch_t = self.delivered_time()

        return 0 if delivered_epoch_t is None else self.value(delivered_epoch_t)

    def loss(self, from_epoch_t: Optional[float] = None, to_epoch_t: Optional[float] = None) -> float:
        """Returns percentage difference between initial value and delivered value, or 0 if undelivered."""

        starting_value = self.value(epoch_t=from_epoch_t)

        if starting_value == 0:
            return 0

        if to_epoch_t is None:
            ending_value = self._delivered_value()
        else:
            ending_value = self.value(epoch_t=to_epoch_t)

        return (ending_value - starting_value) / starting_value

    def __str__(self) -> str:
        return self.task_name if self.task_name else ""

    def reset(self, epoch_start_t: float = 0) -> Self:
        """Returns a clone of the task except history"""
        result = copy.copy(self)

        result.delivered_loss = 0.0
        result.delivered_value = 0.0
        result.creation_sim_t = epoch_start_t
        result.completed_story_points = 0

        result.history = TaskHistory(epoch_start_t=epoch_start_t)
        result._id = Task._generate_id()

        return result

    def remaining_work(self):
        return self.story_points - self.completed_story_points

    def do_work(self, story_points: float):

        # negative story points are allowed to represent regression
        remaining_work = self.remaining_work()

        if story_points <= remaining_work:
            self.completed_story_points += story_points

            if self.completed_story_points < 0:
                raise ValueError("completed_story_points cannot be negative")

            return 0.0

        self.completed_story_points = self.story_points
        return story_points - remaining_work

    def end(self, sim_t: float, event: Optional[WorkflowStateName] = None, status: EventStatus = EventStatus.SUCCESS):

        last_event = self.history.last_event()

        loss = 0 if last_event is None else self.loss(
            from_epoch_t=last_event.time, to_epoch_t=self.history.epoch.to_epoch_time(sim_t))

        self.history.end(sim_time=sim_t, event=event, status=status, loss=loss)

    def start(self, sim_t: float, event: WorkflowStateName):
        self.history.start(sim_time=sim_t, event=event)

    def resume(self, event: WorkflowStateName):
        self.history.resume(event=event)

    def terminate(self, sim_t: float, event: WorkflowStateName, status: EventStatus = EventStatus.SUCCESS):
        self.history.terminate(sim_time=sim_t, event=event, status=status)

        self.delivered_value = self._delivered_value()
        self.delivered_loss = self.loss()


class SupportTask(Task):
    def __init__(self,
                 story_points: float,
                 task_name: Optional[str] = None,
                 creation_time: float = 0.0):

        super().__init__(initial_value=0,
                         story_points=story_points,
                         depreciation_rate=0,
                         task_name=task_name,
                         creation_time=creation_time,
                         task_type=TaskType.SUPPORT)

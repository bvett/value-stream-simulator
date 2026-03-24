import copy
from typing import Self
from .task_history import TaskHistory


class Task:
    """Represents a unit of delivery with depreciating value"""

    def __init__(self,
                 initial_value: float,
                 complexity: float,
                 depreciation_rate=0.005,
                 task_id: str | None = None,
                 creation_time: float = 0.0) -> None:
        """Creates a Task

        Args:
            initial_value (float): Relative value of the task

            complexity (float): Relative complexity of the task

            depreciation_rate (float, optional): Percentage of value 
              decrease per time unit. Defaults to 0.005.

            task_id (str): Public identifier. Optional.

            creation_time (float, optional): Relative time of task creation. Defaults to 0.0.

        """

        self.task_id = task_id

        if initial_value < 0:
            raise ValueError("initial_value must be >=0")

        self._initial_value = initial_value

        if complexity < 0:
            raise ValueError("complexity must be >= 0")

        self.complexity = complexity

        if creation_time < 0:
            raise ValueError("creation_time must be >=0")

        self.creation_t = creation_time

        if not 0 <= depreciation_rate <= 1:
            raise ValueError("depreciation_rate must >=0 and <=1")

        self.depreciation_rate = depreciation_rate

        self.history = TaskHistory()

        self.loss: float = 0.0
        self.delivered_value: float = 0.0

    def value(self, time: float | None = None) -> float:
        """Calculates the value of the task at a specified time

        Args:
            time (float | None, optional): Simulation time. Defaults to None.

        Returns:
            float: depreciated value of the task
        """
        if not time:
            return self._initial_value

        if time < self.creation_t:
            raise ValueError("time must be >= creation_t")

        return self._initial_value * ((1-self.depreciation_rate) ** (time - self.creation_t))

    def delivered_time(self):
        """Returns the time the task was successfully delivered, otherwise None"""
        last_event = self.history.last_event()

        if (last_event is not None) \
                and (last_event.status == last_event.EventStatus.SUCCESS) \
                and last_event.event_type == last_event.EventType.TERMINAL:
            return last_event.time

        return None

    # TODO: make agnostic of workflow states
    def _delivered_value(self) -> float:
        """Returns the depreciated value of the task at the time of delivery, or its initial value if undelivered.
        """

        delivered_t = self.delivered_time()

        return 0 if delivered_t is None else self.value(delivered_t)

    def _loss(self) -> float:
        """Returns percentage decrease in value of a delivered task"""
        initial_value = self.value()

        return (self._delivered_value() - initial_value) / initial_value

    def update_value_and_loss(self):
        self.delivered_value = self._delivered_value()
        self.loss = self._loss()

    def __str__(self) -> str:
        return self.task_id if self.task_id else ""

    def reset(self) -> Self:
        """Returns a clone of the task except history"""
        result = copy.copy(self)
        result.history = TaskHistory()

        result.loss = 0.0
        result.delivered_value = 0.0

        return result

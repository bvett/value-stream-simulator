from typing import Any
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
            raise ValueError("time must be >= self.creation_t")

        return self._initial_value * ((1-self.depreciation_rate) ** (time - self.creation_t))

    # can this be agnostic of the workflow? How would it know what 'delivered' is without a special value?
    def delivered_value(self) -> float:
        """Returns the depreciated value of the task at the time of delivery, or its initial value if undelivered.
        """

        if self.history.delivery_start_t is not None and (self.history.delivery_start_t < self.creation_t):
            raise ValueError("delivery_start_t must be >= task.creation_t")

        if self.history.delivery_start_t is not None and \
            self.history.delivery_end_t is not None and \
                (self.history.delivery_end_t < self.history.delivery_start_t):
            raise ValueError("delivery_start_t must be <= delivery_end_t")

        if self.history.delivery_end_t is not None and self.history.delivery_start_t is None:
            raise ValueError(
                "delivery_start_t must not be None when delivery_end_t is not None")

        return self.value(self.history.delivery_end_t)

    def loss(self) -> float:
        """Returns percentage decrease in value of a delivered task"""
        initial_value = self.value()

        return (self.delivered_value() - initial_value) / initial_value

    def __str__(self) -> str:
        return self.task_id if self.task_id else ""

    def to_dict(self) -> dict[str, Any]:

        custom_additions = {
            "loss": self.loss(), "delivered_value": self.delivered_value()}

        return vars(self) | custom_additions

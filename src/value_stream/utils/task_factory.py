from typing import Literal
import numpy as np
from ..task import Task


class TaskFactory:
    """Utility for creating Tasks"""

    def __init__(self,
                 strategy: Literal['equal', 'sd'],
                 complexity: float | tuple[float, float],
                 initial_value: float = 1.0,
                 depreciation_rate: float = 0.02,
                 shuffle: bool = True) -> None:
        """Creates a TaskFactory

        Args:
            strategy (Literal[&#39;equal&#39;, &#39;sd&#39;]): Creates
            tasks with complexities that are either equal reflect a standard deviation

            complexity (float | tuple[float, float]): 
                When strategy is 'equal' : Single value representing the complexity 
                for all Task objects.

                When strategy is 'sd' : Tuple of (low, high) complexity values.

            initial_value (float, optional): Starting value for all Task objects Defaults to 1.0.

            depreciation_rate (float, optional): Depreciation rate for all 
            Task objects. Defaults to 0.02.

            shuffle (bool, optional): Randomizes the order of the created tasks. Defaults to True.

        """

        valid_strategies = ['equal', 'sd']

        if strategy not in valid_strategies:
            raise ValueError(f"strategy must be one of {valid_strategies}")

        if strategy == 'equal':
            self.complexities = self._equal_complexities
        elif strategy == 'sd':
            self.complexities = self._stdev_complexities

        self.initial_value = initial_value
        self.depreciation_rate = depreciation_rate
        self.complexity = complexity
        self.shuffle = shuffle

    def create(self, count: int) -> list[Task]:
        """Creates Task objects based on TaskFactory configuration

        Args:
            count (int): number of tasks to create

        """
        tasks = []

        complexities = self.complexities(count)

        for i in range(count):
            tasks.append(Task(task_id=f"{i+1}",
                              initial_value=self.initial_value,
                              complexity=complexities[i],
                              depreciation_rate=self.depreciation_rate))

        if self.shuffle is True:
            np.random.shuffle(tasks)

        return tasks

    def _equal_complexities(self, count: int) -> list[float]:

        if not isinstance(self.complexity, (int, float)):
            raise ValueError(
                "complexity must be an int or float when strategy is 'equal'")

        return [self.complexity] * count

    def _stdev_complexities(self, count: int) -> list[float]:

        if not isinstance(self.complexity, tuple) or len(self.complexity) != 2:
            raise ValueError(
                "complexity must be a tuple of (low, high) when strategy is 'sd'"
            )

        return np.random.uniform(low=self.complexity[0],
                                 high=self.complexity[1],
                                 size=count).tolist()

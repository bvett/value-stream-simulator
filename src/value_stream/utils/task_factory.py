from typing import Generator, Any
import numpy as np
from ..task import Task


class TaskFactory:
    """Utility for creating Tasks"""

    def __init__(self,
                 complexity: float | Generator[float, Any, None],
                 initial_value: float = 1.0,
                 depreciation_rate: float = 0.02,
                 shuffle: bool = True) -> None:
        """Creates a TaskFactory

        Args:
            complexity (float | Generator[float, Any, None]): 
                Sets the complexity of the tasks.  If complexity is a float, it is used to 
                set the complexity for all tasks created.

                If complexity is a Generator of floats, each task created will have its 
                complexity set by getting the next value of the provided Generator.

            initial_value (float, optional): Starting value for all Task objects Defaults to 1.0.

            depreciation_rate (float, optional): Depreciation rate for all 
            Task objects. Defaults to 0.02.

            shuffle (bool, optional): Randomizes the order of the created tasks. Defaults to True.

        """

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

        for i in range(count):

            if isinstance(self.complexity, int | float):
                complexity = self.complexity
            else:
                complexity = next(self.complexity)

            tasks.append(Task(task_id=f"{i+1}",
                              initial_value=self.initial_value,
                              complexity=complexity,
                              depreciation_rate=self.depreciation_rate))

        if self.shuffle is True:
            np.random.shuffle(tasks)

        return tasks

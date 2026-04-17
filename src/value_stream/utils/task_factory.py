import random
from .factory import generate_args
from ..task import Task


class TaskFactory:
    """Utility for creating Tasks"""

    def create(self, count: int, shuffle: bool = True, initial_value: float = 1.0,
               depreciation_rate: float = 0.02, **kwargs) -> list[Task]:
        """Creates Task objects based on TaskFactory configuration

        Args:
            count (int): number of tasks to create

            shuffle (bool, optional): Randomizes the order of the created tasks. Defaults to True.

            initial_value (float, optional): Starting value for all Task objects Defaults to 1.0.

            depreciation_rate (float, optional): Depreciation rate for all 
            Task objects. Defaults to 0.02.

            **kwargs: additional arguments to pass to the Task constructor


        """

        if count <= 0:
            raise ValueError("count must be > 0")

        tasks: list[Task] = []

        for i in range(count):

            args = generate_args(**kwargs)

            tasks.append(Task(task_id=f"{i+1}",
                              initial_value=initial_value,
                              depreciation_rate=depreciation_rate,
                              **args))

        if shuffle is True:
            random.shuffle(tasks)

        return tasks

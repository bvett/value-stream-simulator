import random
from typing import Type

from .generator_utils import generate_args
from ..task import Task


class TaskFactory:
    """Utility for creating Tasks"""

    def __init__(self, cls: Type[Task] = Task, **task_kwargs):
        self._task_kwargs = task_kwargs
        self.cls = cls

    def create(self, count: int, shuffle: bool = True) -> list[Task]:
        """Creates Task objects based on TaskFactory configuration

        Args:
            count (int): number of tasks to create

            shuffle (bool, optional): Randomizes the order of the created tasks. Defaults to True.

        """

        if count <= 0:
            raise ValueError("count must be > 0")

        tasks: list[Task] = []

        for i in range(count):

            args = generate_args(**self._task_kwargs)

            if 'task_id' not in args:
                args['task_id'] = f"{i+1}"

            tasks.append(self.cls(**args))

        if shuffle is True:
            random.shuffle(tasks)

        return tasks

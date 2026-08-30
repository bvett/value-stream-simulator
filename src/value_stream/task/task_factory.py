import random
from typing import Type, Optional

from simpy import Environment

from value_stream.utils import generate_args
from .task import Task


class TaskFactory:
    """Utility for creating Tasks"""

    def __init__(self, cls: Type[Task] = Task, env: Optional[Environment] = None, **task_kwargs):
        """Initializes a TaskFactory

        Args:
            cls (Type[Task], optional): Creates objects of this class. Defaults to Task.
            env (Optional[Environment], optional): If provided, 
                used for setting creation_sim_t of the tasks. Defaults to None.
        """
        self._task_kwargs = task_kwargs
        self.cls = cls
        self.env = env

        if (env is not None) and ('creation_sim_t' in task_kwargs):
            raise ValueError("env and creation_sim_t are mutually exclusive")

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

            if 'task_name' not in args:
                args['task_name'] = f"{i+1}"

            if self.env is not None:
                args['creation_sim_t'] = self.env.now

            tasks.append(self.cls(**args))

        if shuffle is True:
            random.shuffle(tasks)

        return tasks

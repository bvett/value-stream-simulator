from typing import Any, Type, Optional
import random

from simpy import Environment

from value_stream.task import Task

from .factory import Factory


class TaskFactory(Factory):
    """Utility for creating Tasks"""

    def __init__(self, cls: Type[Task] = Task, **task_kwargs: Any) -> None:
        """Initializes a TaskFactory.

        Args:
            **task_kwargs (Any): Default task constructor arguments.
        """

        self._task_kwargs = task_kwargs
        self.cls = cls

    def create(
        self, count: int, env: Optional[Environment] = None, shuffle: bool = True
    ) -> list[Task]:
        """Creates Task objects based on TaskFactory configuration.

        Args:
            count (int): Number of objects to create.
            env (Optional[Environment]): Simulation environment.
            shuffle (bool): Whether to randomize the created task order.

        Raises:
            ValueError: If count is not positive or environment time conflicts with creation_sim_t.

        Returns:
            list[Task]: Tasks created with this factory configuration.
        """

        if count <= 0:
            raise ValueError("count must be > 0")

        if (env is not None) and ("creation_sim_t" in self._task_kwargs):
            raise ValueError("env and creation_sim_t are mutually exclusive")

        tasks: list[Task] = []

        for i in range(count):

            args = self._generate_args(**self._task_kwargs)

            if "task_name" not in args:
                args["task_name"] = f"{i+1}"

            if env is not None:
                args["creation_sim_t"] = env.now

            tasks.append(self.cls(**args))

        if shuffle is True:
            random.shuffle(tasks)

        return tasks

import random
from typing import Generator, Type
from simpy import Environment, Interrupt, Process, Store

from .factory import generate_args
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


class TaskGenerator:
    """creates a set of Tasks on a regular interval.  Useful for simulating task creation over time, or 
    the creation of unexpected toil.
    """

    def __init__(self, group_size: int = 1, shuffle: bool = True, **kwargs):
        self.group_size = group_size
        self.shuffle = shuffle
        self.kwargs = kwargs

        self.proc: Process | None = None

    def __iter__(self):
        return self

    def __next__(self):
        return TaskFactory(**self.kwargs).create(count=self.group_size, shuffle=self.shuffle)

    def start(self, env: Environment, interval: float | Generator, target: Store):
        def gen():
            while True:

                if isinstance(interval, Generator):
                    i = next(interval)
                else:
                    i = interval

                try:
                    value: list[Task] = next(self)
                    event = env.timeout(delay=i, value=value)
                    yield event

                    if event.value is None:
                        raise RuntimeError("Unexpected empty value")

                    for v in event.value:
                        target.put(v)

                except Interrupt:
                    break
        self.proc = env.process(gen())

    def stop(self):
        if self.proc is not None:
            self.proc.interrupt()

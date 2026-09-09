from abc import ABC, abstractmethod
from typing import Literal
from value_stream.task import Task


class ResourcePolicy(ABC):
    @abstractmethod
    def task_priority(self, tasks_1: list[Task], tasks_2: list[Task]) -> Literal[0] | Literal[1] | Literal[-1]:
        pass

from abc import ABC, abstractmethod

from value_stream.task import Task
from .assignment_strategy import AssignmentStrategy


class WorkflowPolicy(ABC):

    @abstractmethod
    def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
        pass

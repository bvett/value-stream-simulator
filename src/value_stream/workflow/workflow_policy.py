from abc import ABC, abstractmethod

from value_stream.policy import AssignmentStrategy
from value_stream.task import Task


class WorkflowPolicy(ABC):

    @abstractmethod
    def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
        pass

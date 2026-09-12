from abc import abstractmethod
from typing import Literal

from value_stream.resources import ResourcePolicy
from value_stream.task import Task
from value_stream.workflow import WorkflowPolicy, AssignmentStrategy


class SimulationPolicy(ResourcePolicy, WorkflowPolicy):
    """encapsulates control logic for a simulation"""

    @abstractmethod
    def task_priority(self, tasks_1: list[Task], tasks_2: list[Task]) -> Literal[0] | Literal[1] | Literal[-1]:
        pass

    @abstractmethod
    def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
        pass

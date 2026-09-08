from value_stream.resources import ResourcePolicy
from value_stream.task import Task
from value_stream.workflow import WorkflowPolicy

from .assignment_strategy import AssignmentStrategy


class SimulationPolicy(ResourcePolicy, WorkflowPolicy):
    """encapsulates control logic for a simulation"""

    def task_priority(self, tasks_1: list[Task], tasks_2: list[Task]):
        raise NotImplementedError

    def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
        raise NotImplementedError

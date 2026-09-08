from value_stream.task import Task

from .assignment_strategy import AssignmentStrategy


class WorkflowPolicy:

    def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
        raise NotImplementedError

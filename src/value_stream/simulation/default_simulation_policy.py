from typing import Literal

from value_stream.task import Task, TaskType
from value_stream.policy import SimulationPolicy
from value_stream.workflow import AssignmentStrategy


class DefaultSimulationPolicy(SimulationPolicy):
    """encapsulates control logic for a simulation"""

    def task_priority(
        self, tasks_1: list[Task], tasks_2: list[Task]
    ) -> Literal[0] | Literal[1] | Literal[-1]:
        """Compares two Task lists and returns an indicator of which has higher priority.

        Args:
            tasks_1 (list[Task]): Tasks 1.
            tasks_2 (list[Task]): Tasks 2.

        Returns:
            Literal[0] | Literal[1] | Literal[-1]: -1 if tasks_1 is of higher priority,
        """

        # handle use-cases when one or both lists are empty
        if (not tasks_1) and (not tasks_2):
            return 0

        if not tasks_1:
            return 1

        if not tasks_2:
            return -1

        # assume homogeneous collections regarding TaskType
        # 1) support is a higher priortiy than development
        # 2) support (in tasks_1) is a higher priority than support (in tasks_2)
        # 3) development is the same priority as development

        tt_1 = tasks_1[0].task_type
        tt_2 = tasks_2[0].task_type

        if tt_1 == TaskType.SUPPORT:
            return -1

        if tt_2 == TaskType.SUPPORT:
            return 1

        return 0

    def support_assignment_strategy(self, tasks: list[Task]) -> AssignmentStrategy:
        """Choose an assignment strategy for support tasks.

        Args:
            tasks (list[Task]): Tasks to process.

        Returns:
            AssignmentStrategy: Strategy selected for assigning the support tasks.
        """
        if tasks:
            task = tasks[0]

            if (task.task_type == TaskType.DEVELOPMENT) and (task.is_rework is True):
                return AssignmentStrategy.OWNER

            if task.task_type == TaskType.SUPPORT:
                return AssignmentStrategy.RANDOM

        return AssignmentStrategy.NEXT_AVAILABLE

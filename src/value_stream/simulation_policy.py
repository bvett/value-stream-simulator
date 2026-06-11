from .task import Task, TaskType


class SimulationPolicy:
    """encapsulates control logic for a simulation"""

    def priority(self, tasks_1: list[Task], tasks_2: list[Task]):
        raise NotImplementedError


class DefaultSimulationPolicy(SimulationPolicy):
    """encapsulates control logic for a simulation"""

    def priority(self, tasks_1: list[Task], tasks_2: list[Task]):
        """Compares two Task lists and returns an indicator of which has higher priority

        Returns:
            int: -1 if tasks_1 is of higher priority, 
            0 if tasks_1 and tasks_2 are of equal priority, and 
            1 if tasks_2 is of higher priority
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

# Parent class for Developer and Toolchain
from simpy import Environment, Store

from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Resource:
    """Base class for simulation objects that operate on tasks"""

    def __init__(self, workflow_state: WorkflowStateName):
        self.workflow_state = workflow_state

    def operate(self, env: Environment, tasks: list[Task], target: Store):
        """Simulates an action on a task object"""
        for task in tasks:
            task.history.start(env.now, self.workflow_state)

        yield env.timeout(self.effort(tasks))

        for task in tasks:
            task.history.end(env.now, self.workflow_state)
            yield target.put(task)

    def effort(self, tasks: list[Task]):
        """Used in derived classes to provide the amount of simulation time
        spent operating on a task."""
        raise NotImplementedError()

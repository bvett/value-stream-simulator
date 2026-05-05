# Parent class for Developer and Toolchain
from simpy import Environment, Store

from ..event_status import EventStatus
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Resource:
    """Base class for simulation objects that operate on tasks"""

    def __init__(self, workflow_state: WorkflowStateName):
        self.workflow_state = workflow_state

    def operate(self, env: Environment, tasks: list[Task], target: Store, target_upon_failure: Store | None = None):
        """Simulates an action on a task object"""
        for task in tasks:
            task.history.start(env.now, self.workflow_state)

        result = env.process(self.do_work(env, tasks))
        yield result

        if result.value is not None:
            status = result.value['result']
        else:
            status = EventStatus.SUCCESS

        destination = target

        if (status == EventStatus.FAILURE) and (target_upon_failure is not None):
            destination = target_upon_failure

        for task in tasks:
            task.history.end(env.now, self.workflow_state, status=status)
            yield destination.put(task)

    def do_work(self, env: Environment, tasks: list[Task]):
        raise NotImplementedError()

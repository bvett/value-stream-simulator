# Parent class for Developer and Toolchain
from simpy import Environment, Event, Interrupt, Store

from ..event_status import EventStatus
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Resource:
    """Base class for simulation objects that operate on tasks"""

    def __init__(self, workflow_state: WorkflowStateName):
        self.workflow_state = workflow_state
        self._process = None
        self._suspended_work: list[Event] = []

    def operate(self, env: Environment, tasks: list[Task], target: Store, target_upon_failure: Store | None = None):
        """Simulates an action on a task object"""
        for task in tasks:
            task.history.start(env.now, self.workflow_state)

        # interrupt any work-in-progress.
        if self._process is not None and self._process.is_alive:
            self._process.interrupt()

        status = EventStatus.SUCCESS

        while True:
            self._process = env.process(self.do_work(env, tasks))
            try:
                yield self._process
                if self._process.value is not None:
                    status = self._process.value['result']
                break
            except Interrupt:
                # push a semaphore onto the stack and resume when triggered
                semaphore = Event(env)
                self._suspended_work.append(semaphore)
                yield semaphore

        destination = target

        if (status == EventStatus.FAILURE) and (target_upon_failure is not None):
            destination = target_upon_failure

        for task in tasks:
            task.history.end(env.now, self.workflow_state, status=status)
            yield destination.put(task)

        # after completing a task, check for suspended work and trigger resumption
        if self._suspended_work:
            e = self._suspended_work.pop()
            e.succeed()

    def do_work(self, env: Environment, tasks: list[Task]):
        raise NotImplementedError()

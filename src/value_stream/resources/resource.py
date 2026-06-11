# Parent class for Developer and Toolchain
from simpy import Environment, Event, Interrupt, Process, Store
from simpy.events import ProcessGenerator

from ..event_status import EventStatus
from ..simulation_policy import SimulationPolicy
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class Resource:
    """Base class for simulation objects that operate on tasks"""

    def __init__(self, workflow_state: WorkflowStateName, resource_id: str | None = None):
        self.workflow_state = workflow_state
        self._process: Resource.ProcessWrapper | None = None
        self._suspended_work: list[Event] = []
        self.id = resource_id

    def operate(self, env: Environment, tasks: list[Task],
                target: Store,
                policy: SimulationPolicy,
                target_upon_failure: Store | None = None):
        """Simulates an action on a task object"""

        for task in tasks:
            task.history.start(env.now, self.workflow_state)

        if self._process is not None and self._process.is_alive:

            if policy.priority(tasks, self._process.tasks) == -1:
                self._process.interrupt()
            else:
                # if what's in progress is of higher priority, queue up current work
                yield env.process(self._pause(env))

        while True:
            status = EventStatus.SUCCESS
            self._process = self._create_process(env, tasks)

            try:
                yield self._process
            except Interrupt:

                # if do_work is interrupted, wait on a signal that will
                # be triggered once this resource has processed all
                # subsequent interruptions
                yield env.process(self._pause(env))

                continue

            if self._process.value is not None:
                status = self._process.value['result']

            self._process = None

            destination = target

            if (status == EventStatus.FAILURE) and (target_upon_failure is not None):
                destination = target_upon_failure

            for task in tasks:
                task.history.end(env.now, self.workflow_state, status=status)

                yield destination.put(task)

            # once work is complete, check for previously interrupted work
            # and trigger resumption
            if self._suspended_work:
                signal = self._suspended_work[-1]
                signal.succeed()

            break

    def do_work(self, env: Environment, tasks: list[Task]):
        raise NotImplementedError()

    def _pause(self, env: Environment):
        while True:
            signal = env.event()
            self._suspended_work.append(signal)

            yield signal

            self._suspended_work.pop()

            if self._process is None:
                break

    def _create_process(self, env: Environment, tasks: list[Task]):
        return Resource.ProcessWrapper(env, tasks, self.do_work(env, tasks))

    class ProcessWrapper(Process):
        def __init__(self, env: Environment, tasks: list[Task], generator: ProcessGenerator):
            super().__init__(env, generator)
            self.tasks = tasks

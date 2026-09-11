# Parent class for Developer and Toolchain
from abc import ABC, abstractmethod

from typing import Any, Generator, Optional
import uuid

from simpy import Environment, Event, Interrupt, Process, Timeout
from simpy.events import ProcessGenerator

from value_stream.task import TaskState
from value_stream.task import EventStatus, Task, TaskRouter

from .resource_policy import ResourcePolicy
from .resource_tracker import ResourceTracker


class Resource(ABC):
    """Base class for simulation objects that operate on tasks"""

    @classmethod
    def _generate_id(cls) -> uuid.UUID:
        return uuid.uuid4()

    def __init__(self):
        self._process: Optional[Resource.ProcessWrapper] = None
        self._suspended_work: list[Event] = []
        self.idle_t = 0
        self._id = Resource._generate_id()

    @property
    def resource_id(self) -> uuid.UUID:
        return self._id

    def operate(self, env: Environment, tasks: list[Task],
                task_router: TaskRouter,
                policy: ResourcePolicy,
                workflow_state: TaskState,
                tracker: Optional[ResourceTracker] = None):
        """Simulates an action on a task object"""

        for task in tasks:
            task.start(env.now, workflow_state, resource_id=self._id)

        if (self._process is not None) and (not self._process.processed):
            if policy.task_priority(tasks, self._process.tasks) == -1:
                self._process.interrupt()
            else:
                # if what's in progress is of higher priority, queue up current work
                # yield self._process ....
                yield env.process(self._pause(env))

        while True:
            status = EventStatus.SUCCESS
            self._process = self._create_process(env, tasks)

            start_t = env.now
            try:
                if tracker is not None:
                    tracker.start_work(
                        workflow_state, env.now-self.idle_t)
                yield self._process

                if self._process.value is not None:
                    status = self._process.value['result']

            except Interrupt:

                # if do_work is interrupted, wait on a signal that will
                # be triggered once this resource has processed all
                # subsequent interruptions

                interruption_start_t = env.now
                if tracker is not None:
                    tracker.complete_work(
                        workflow_state, status, elapsed_t=env.now-start_t)
                yield env.process(self._pause(env))
                if tracker is not None:
                    tracker.interruption(
                        workflow_state, elapsed_t=env.now - interruption_start_t)

                continue

            if tracker is not None:
                tracker.complete_work(
                    workflow_state, status, elapsed_t=env.now-start_t)
            self.idle_t = env.now

            for task in tasks:
                task.end(env.now, workflow_state,
                         status=status, resource_id=self._id)

                if (status == EventStatus.FAILURE):
                    yield task_router.route(task=task.as_rework(), status=status)
                else:
                    yield task_router.route(task=task.clear_rework(), status=status)

            # once work is complete, check for previously interrupted work
            # and trigger resumption
            if self._suspended_work:
                signal = self._suspended_work[-1]
                signal.succeed()

            break

    @abstractmethod
    def do_work(self, env: Environment, tasks: list[Task]) -> Generator[Timeout, Any, None]:
        pass

    def _pause(self, env: Environment):
        while True:
            signal = env.event()
            self._suspended_work.append(signal)

            yield signal

            self._suspended_work.pop()

            if (self._process is not None) and (self._process.target is None):
                break

    def _create_process(self, env: Environment, tasks: list[Task]):
        return Resource.ProcessWrapper(env, tasks, self.do_work(env, tasks))

    class ProcessWrapper(Process):
        def __init__(self, env: Environment, tasks: list[Task], generator: ProcessGenerator):
            super().__init__(env, generator)
            self.tasks = tasks

from typing import Iterable, Optional

from simpy import Environment, Interrupt, Process
from simpy.resources.store import StoreGet

from value_stream.task import TaskState
from value_stream.resources import Resource, ResourceTracker, ResourcePolicy
from value_stream.task import Task, TaskRouter

from .pool_manager import PoolManager
from .task_store import TaskStore
from .workflow_policy import WorkflowPolicy


class ResourceOperator:
    """Handles the allocation of Resource objects that operate on 
    Tasks during a simulation"""

    def __init__(self, env: Environment,
                 resources: Iterable[Resource],
                 workflow_policy: WorkflowPolicy,
                 resource_policy: ResourcePolicy,
                 tracker: Optional[ResourceTracker] = None,
                 cadence: int = 0):
        self.env = env
        self._queue: list[Task] = []

        self.pool_manager = PoolManager(
            self.env, resources=iter(resources), policy=workflow_policy, tracker=tracker)
        # self.resource_generator = iter(resources)

        if cadence < 0:
            raise ValueError("cadence must be >= 0")

        self.cadence = cadence
        self.trigger = env.event()

        # enables cleanup of internal processes
        self._monitor_p: Optional[Process] = None
        self._timer_p: Optional[Process] = None
        self._executor_p: Optional[Process] = None

        self.workflow_policy = workflow_policy
        self.resource_policy = resource_policy

        self._source: Optional[TaskStore] = None

        self._tracker = tracker

    def start(self, source: TaskStore, workflow_state: TaskState, task_router: TaskRouter):
        """Starts processing loop that:
            1) Waits for tasks to appear in source
            2) Triggers execution on a fixed schedule or continuously
            3) Requests a resource to operate on the task
            4) Waits for the resource to operate on the task
            5) Releases the resource"""

        if self._monitor_p is not None:
            raise RuntimeError("manager cannot be restarted")

        self._source = source
        self._monitor_p = self.env.process(self._monitor(source))

        # Simulates "release train" - changes are collected
        # and deployed during regular release windows

        if self.cadence > 0:
            self._timer_p = self.env.process(self._timer())

        self._executor_p = self.env.process(self._executor(workflow_state=workflow_state,
                                                           task_router=task_router))

    def stop(self) -> None:
        """Shutdown the manager

        Raises:
            RuntimeError: if start() has not been called prior
        """
        if self._monitor_p is None or self._executor_p is None:
            raise RuntimeError(
                "attempt to stop a manager that has not been started")

        if self._monitor_p.is_alive:
            self._monitor_p.interrupt()

        if self._executor_p.is_alive:
            self._executor_p.interrupt()

        if (self._timer_p is not None) and (self._timer_p.is_alive):
            self._timer_p.interrupt()

    def _monitor(self, source: TaskStore):

        while True:
            source_request = None
            try:

                # wait for an item to arrive via source queue
                source_request = source.get()
                task: Task = yield source_request

                task.resume(source.name)
                self._queue.append(task)

                if self.cadence == 0:
                    # do this based on cadence
                    self.trigger.succeed(self._queue.copy())
                    self._queue.clear()
                    self.trigger = self.env.event()

            except Interrupt:

                # cancel the source_request to prevent item from
                # being swallowed between start() invocations

                if source_request is not None:
                    source_request.cancel()
                break

    def _timer(self):
        while True:
            try:
                yield self.env.timeout(self.cadence)
                if len(self._queue) == 0:
                    continue

                self.trigger.succeed(value=self._queue.copy())
                self._queue.clear()
                self.trigger = self.env.event()

            except Interrupt:
                break

    def _executor(self, workflow_state: TaskState, task_router: TaskRouter):

        while True:
            try:
                tasks: list[Task] = yield self.trigger  # wait for work

                self.env.process(self._execute(workflow_state=workflow_state, tasks=tasks,
                                               task_router=task_router))
            except Interrupt:
                break

    def _execute(self, workflow_state: TaskState, tasks: list[Task], task_router: TaskRouter):

        wait_t = self.env.now

        if self._tracker is not None:
            self._tracker.start_waiting(workflow_state)

        r = self.pool_manager.request(workflow_state, tasks=tasks)

        if isinstance(r, StoreGet):
            resource = yield r
        else:
            resource = r

        if self._tracker is not None:
            self._tracker.complete_waiting(workflow_state,
                                           self.env.now - wait_t)

        for task in tasks:
            task.end(self.env.now)

        yield self.env.process(resource.operate(env=self.env,
                                                tasks=tasks,
                                                workflow_state=workflow_state,
                                                task_router=task_router,
                                                policy=self.resource_policy,
                                                tracker=self._tracker))

        if isinstance(r, StoreGet):
            self.pool_manager.release(resource)

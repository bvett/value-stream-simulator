from typing import Iterable

from simpy import Environment, Interrupt, Store

from . import Resource
from ..simulation_policy import SimulationPolicy
from ..task import Task
from ..workflow_state import WorkflowState


class ResourceOperator:
    """Handles the allocation of Resource objects that operate on 
    Tasks during a simulation"""

    def __init__(self, env: Environment,
                 resources: Iterable[Resource],
                 policy: SimulationPolicy,
                 cadence: int = 0):
        self.env = env
        self._queue: list[Task] = []

        self.resource_pool = Store(self.env)
        self.resource_generator = iter(resources)

        if cadence < 0:
            raise ValueError("cadence must be >= 0")

        self.cadence = cadence
        self.trigger = env.event()

        # enables cleanup of internal processes
        self._monitor_p = None
        self._timer_p = None
        self._executor_p = None

        self.policy = policy

    def start(self, source: WorkflowState, target: WorkflowState, target_upon_failure: WorkflowState | None = None):
        """Starts processing loop that:
            1) Waits for tasks to appear in source
            2) Triggers execution on a fixed schedule or continuously
            3) Requests a resource to operate on the task
            4) Waits for the resource to operate on the task
            5) Releases the resource"""

        if self._monitor_p is not None:
            raise RuntimeError("manager cannot be restarted")

        self._monitor_p = self.env.process(self._monitor(source))

        # Simulates "release train" - changes are collected
        # and deployed during regular release windows

        if self.cadence > 0:
            self._timer_p = self.env.process(self._timer())

        self._executor_p = self.env.process(self._executor(
            target, target_upon_failure=target_upon_failure))

    def stop(self) -> None:
        """Shutdown the manager

        Raises:
            RuntimeError: if start() has not been called prior
        """
        if self._monitor_p is None or self._executor_p is None:
            raise RuntimeError(
                "attempt to stop a manager that has not been started")

        self._monitor_p.interrupt()
        self._executor_p.interrupt()

        if self._timer_p is not None:
            self._timer_p.interrupt()

    def _monitor(self, source: WorkflowState):
        ingested: int = 0

        while True:
            source_request = None
            try:

                # wait for an item to arrive via source queue
                source_request = source.get()
                task: Task = yield source_request

                task.history.resume(source.name)
                self._queue.append(task)

                ingested += 1

                if self.cadence == 0:
                    self.trigger.succeed()  # do this based on cadence
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

                self.trigger.succeed()
                self.trigger = self.env.event()

            except Interrupt:
                break

    def _executor(self, target: WorkflowState, target_upon_failure: WorkflowState | None = None):

        while True:
            try:
                yield self.trigger  # wait for work
                self.env.process(self._execute(
                    target, target_upon_failure=target_upon_failure))
            except Interrupt:
                break

    def _execute(self, target: WorkflowState, target_upon_failure: WorkflowState | None = None):

        tasks = self._queue.copy()
        self._queue.clear()
        resource: Resource = yield self.request()

        for task in tasks:
            task.history.end(self.env.now)

        yield self.env.process(resource.operate(env=self.env,
                                                tasks=tasks,
                                                target=target,
                                                target_upon_failure=target_upon_failure,
                                                policy=self.policy))

        self.release(resource)

    def request(self):
        """Returns a resource from the resource pool, or waits until one is available. 
        If the pool is empty, generates a new resource from the resource generator 
        and adds it to the pool before returning."""

        if len(self.resource_pool.items) == 0:

            new_item = next(self.resource_generator, None)

            if new_item is not None:
                self.resource_pool.put(new_item)

        return self.resource_pool.get()

    def release(self, operator: Resource):
        return self.resource_pool.put(operator)

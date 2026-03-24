from simpy import Environment

from ..resources import Resource
from ..task import Task
from ..workflow_state import WorkflowState


class Manager:
    """Handles the allocation of Resource objects that operate on 
    Tasks during a simulation"""

    def __init__(self, env: Environment, cadence: int = 0):
        self.env = env
        self._queue: list[Task] = []
        self.cadence = cadence
        self.trigger = env.event()

    def start(self, source: WorkflowState, target: WorkflowState):
        """Starts processing loop that:
            1) Waits for tasks to appear in source
            2) Triggers execution on a fixed schedule or continuously
            3) Requests a resource to operate on the task
            4) Waits for the resource to operate on the task
            5) Releases the resource"""

        self.env.process(self._monitor(source))

        # Simulates "release train" - changes are collected
        # and deployed during regular release windows

        if self.cadence > 0:
            self.env.process(self._timer())

        self.env.process(self._executor(target))

    def _monitor(self, source: WorkflowState):
        while True:
            task: Task = yield source.get()
            task.history.resume(source.name)
            self._queue.append(task)

            if self.cadence == 0:
                self.trigger.succeed()  # do this based on cadence
                self.trigger = self.env.event()

    def _timer(self):
        while True:
            yield self.env.timeout(self.cadence)
            self.trigger.succeed()
            self.trigger = self.env.event()

    def _executor(self, target: WorkflowState):

        while True:
            yield self.trigger  # wait for work
            self.env.process(self._execute(target))

    def _execute(self, target: WorkflowState):

        tasks = self._queue.copy()
        self._queue.clear()
        resource = yield self.request()

        for task in tasks:
            task.history.end(self.env.now)

        yield self.env.process(resource.operate(self.env, tasks, target))
        yield self.release(resource)

    def request(self):
        raise NotImplementedError()

    def release(self, operator: Resource):
        raise NotImplementedError()

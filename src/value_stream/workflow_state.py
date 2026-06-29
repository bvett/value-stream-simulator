from typing import Optional

from simpy import Environment, Event, Store
from simpy.resources.store import StorePut, StoreGet

from .workflow_state_name import WorkflowStateName

from .task import Task


class WorkflowState(Store):
    """Collection of Task objects in the same simulation workflow state.

    Adds start/end events to the task history upon entry/exit
    """

    def __init__(self, env: Environment, name: WorkflowStateName):
        super().__init__(env)
        self.name = name

        self._limit = None
        self._signal: Optional[Event] = None
        self._baseline = 0

    def put(self, item: Task) -> StorePut:

        result = super().put(item)
        if self._limit is not None and self._signal is not None:
            if self._signal.processed:
                raise ValueError("attempt to put after alarm raised")

            # silently block additional items from being added
            #   while waiting for signal to be processed
            if self._signal.triggered:
                self.items.pop()
                result.cancel()
                return result

        item.history.start(self._env.now, self.name)

        if self._limit is not None and self._signal is not None:
            if len(self.items) == self._limit:
                self._signal.succeed(value=self.items[self._baseline:])

        return result

    def get(self):

        def record_history(event: StoreGet):
            task: Optional[Task] = event.value
            if task is None:
                raise RuntimeError("value is None")

            task.history.end(self._env.now, self.name)

        task = super().get()
        task.callbacks = [record_history]

        return task

    def set_alarm(self, limit: int, signal: Event):
        """raises signal when limit items are in this WorkflowState.
        value of signal is a list of Tasks that have been added since the last alarm"""

        if limit <= len(self.items):
            raise ValueError("limit has already been exceeded")

        if signal.triggered:
            raise ValueError("alarm signal has already been triggered")

        self._limit = limit
        self._signal = signal
        self._baseline = len(self.items)


class TerminalWorkflowState(WorkflowState):
    """Represents an end-state of a workflow.  Tasks enter, but do not exit"""

    def __init__(self, env: Environment, name: WorkflowStateName):
        super().__init__(env, name)
        self.name = name

    def put(self, item: Task) -> StorePut:
        result = Store.put(self, item)
        if self._limit is not None and self._signal is not None:
            if self._signal.processed:
                raise ValueError("attempt to put after alarm raised")

            if self._signal.triggered:
                self.items.pop()
                result.cancel()
                return result

        item.history.terminate(self._env.now, self.name)
        item.update_value_and_loss()

        if self._limit is not None and self._signal is not None:
            if len(self.items) == self._limit:
                self._signal.succeed(value=self.items[self._baseline:])

        return result

    def get(self):
        raise NotImplementedError()

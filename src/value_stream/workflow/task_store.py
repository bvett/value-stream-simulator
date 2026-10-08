from typing import Optional

from simpy import Environment, Event, Store
from simpy.resources.store import StorePut, StoreGet

from value_stream.task import TaskState
from value_stream.task import Task


class TaskStore(Store):
    """Collection of Task objects in the same simulation workflow state.

    Adds start/end events to the task history upon entry/exit
    """

    def __init__(self, env: Environment, name: TaskState) -> None:
        """Create a task store for one workflow state.

        Args:
            env (Environment): Simulation environment.
            name (TaskState): Name of the workflow state.
        """
        super().__init__(env)
        self.name = name

        self._limit = None
        self._signal: Optional[Event] = None
        self._baseline = 0

    def put(self, item: Task) -> StorePut:
        """Add an item to the store.

        Args:
            item (Task): Task to add to the store.

        Raises:
            ValueError: If an item is added after the store alarm has been processed.

        Returns:
            StorePut: StorePut event scheduled for the task.
        """
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

        item.start(self._env.now, self.name)

        if self._limit is not None and self._signal is not None:
            if len(self.items) == self._limit:
                self._signal.succeed(value=self.items[self._baseline :])

        return result

    def get(self) -> StoreGet:
        """Remove the next task and record its workflow end event."""

        def record_history(event: StoreGet):
            # since this is a callback function that is invoked
            # after the event is triggered, event.value will be valid
            task: Task = event.value  # pyright: ignore[reportAssignmentType]
            task.end(self._env.now, self.name)

        task = super().get()
        task.callbacks = [record_history]

        return task

    def set_alarm(self, limit: int, signal: Event) -> None:
        """Trigger a signal when the store reaches the requested item count.

        Args:
            limit (int): Store size that triggers the signal.
            signal (Event): Event to trigger when the limit is reached.

        Raises:
            ValueError: If the item limit has already been reached or the signal has triggered.
        """

        if limit <= len(self.items):
            raise ValueError("limit has already been exceeded")

        if signal.triggered:
            raise ValueError("alarm signal has already been triggered")

        self._limit = limit
        self._signal = signal
        self._baseline = len(self.items)


class TerminalTaskStore(TaskStore):
    """Represents an end-state of a workflow.  Tasks enter, but do not exit"""

    def __init__(self, env: Environment, name: TaskState):
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

        item.terminate(self._env.now, self.name)

        if self._limit is not None and self._signal is not None:
            if len(self.items) == self._limit:
                self._signal.succeed(value=self.items[self._baseline :])

        return result

    def get(self):
        raise NotImplementedError()

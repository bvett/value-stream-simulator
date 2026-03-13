from simpy import Environment, Store
from simpy.resources.store import StorePut, StoreGet

from .workflow_state_name import WorkflowStateName

from .task import Task


class WorkflowState(Store):

    def __init__(self, env: Environment, name: WorkflowStateName):
        super().__init__(env)
        self.name = name

    def put(self, item: Task) -> StorePut:
        item.history.start(self.name, self._env.now)
        return super().put(item)

    def get(self):

        def record_history(event: StoreGet):
            task: Task | None = event.value
            if task is None:
                raise RuntimeError("value is None")

            task.history.end(self.name, self._env.now)

        task = super().get()
        task.callbacks = [record_history]

        return task


class TerminalWorkflowState(Store):
    def __init__(self, env: Environment, name: WorkflowStateName):
        super().__init__(env)
        self.name = name

    def put(self, item: Task) -> StorePut:
        item.history.terminate(self.name, self._env.now)
        item.update_value_and_loss()
        return super().put(item)

    def get(self):
        raise NotImplementedError()

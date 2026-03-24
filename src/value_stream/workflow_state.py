from simpy import Environment, Store
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

    def put(self, item: Task) -> StorePut:
        item.history.start(self._env.now, self.name)
        return super().put(item)

    def get(self):

        def record_history(event: StoreGet):
            task: Task | None = event.value
            if task is None:
                raise RuntimeError("value is None")

            task.history.end(self._env.now, self.name)

        task = super().get()
        task.callbacks = [record_history]

        return task


class TerminalWorkflowState(WorkflowState):
    """Represents an end-state of a workflow.  Tasks enter, but do not exit"""

    def __init__(self, env: Environment, name: WorkflowStateName):
        super().__init__(env, name)
        self.name = name

    def put(self, item: Task) -> StorePut:
        item.history.terminate(self._env.now, self.name)
        item.update_value_and_loss()
        return Store.put(self, item)

    def get(self):
        raise NotImplementedError()

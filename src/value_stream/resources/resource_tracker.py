from typing import Optional

from simpy import Environment

from value_stream.core import EventStatus, WorkflowStateName

from .resource_metadata import ResourceMetadata


class ResourceTracker:

    def __init__(self, env: Environment):
        self._env = env
        self._epoch_t = env.now
        self._data: list[ResourceMetadata] = []

    @property
    def data(self):
        return self._data.copy()

    def register(self, workflow_state: WorkflowStateName):
        self._data.append(ResourceMetadata(time=self._env.now - self._epoch_t,
                                           state=workflow_state, allocated=1))

    def start_work(self, workflow_state: WorkflowStateName, elapsed_t: float):
        self._data.append(ResourceMetadata(time=self._env.now - self._epoch_t,
                                           state=workflow_state, active=1, idle_t=elapsed_t))

    def complete_work(self, workflow_state: WorkflowStateName, status: EventStatus, elapsed_t: Optional[float] = None):

        if status == EventStatus.FAILURE:
            self._data.append(ResourceMetadata(time=self._env.now - self._epoch_t,
                                               state=workflow_state, active=-1, failure_t=elapsed_t))
        else:
            self._data.append(ResourceMetadata(time=self._env.now - self._epoch_t,
                                               state=workflow_state, active=-1, success_t=elapsed_t))

    def interruption(self, workflow_state: WorkflowStateName, elapsed_t: float):
        self._data.append(ResourceMetadata(time=self._env.now - self._epoch_t,
                                           state=workflow_state, interruption_t=elapsed_t))

    def waiting(self, workflow_state: WorkflowStateName, waiting_t: float):
        self._data.append(ResourceMetadata(time=self._env.now - self._epoch_t,
                                           state=workflow_state, waiting_t=waiting_t))

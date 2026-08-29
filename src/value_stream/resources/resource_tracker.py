from typing import Optional, Self

from simpy import Environment

from value_stream.core import EventStatus, WorkflowStateName

from .resource_metadata import ResourceMetadata


class ResourceTracker:

    _instance: Optional[Self] = None

    @classmethod
    def init(cls, env: Environment):
        cls._instance = cls(env)

    @classmethod
    def get(cls) -> Self:
        if cls._instance is None:
            raise RuntimeError("ResourceTracker not initialized")

        return cls._instance

    def __init__(self, env: Environment):
        self._env = env
        self.epoch_t: float = 0
        self.data: list[ResourceMetadata] = []

    @classmethod
    def start_epoch(cls):
        instance = cls.get()
        instance.data.clear()
        instance.epoch_t = instance._env.now

    @classmethod
    def _epoch_time(cls):
        instance = cls.get()
        return instance._env.now - instance.epoch_t

    @classmethod
    def register(cls, workflow_state: WorkflowStateName):
        instance = cls.get()
        instance.data.append(ResourceMetadata(time=instance._epoch_time(),
                                              state=workflow_state, allocated=1))

    @classmethod
    def start_work(cls, workflow_state: WorkflowStateName, elapsed_t: float):
        instance = cls.get()
        instance.data.append(ResourceMetadata(time=instance._epoch_time(),
                                              state=workflow_state, active=1, idle_t=elapsed_t))

    @classmethod
    def complete_work(cls, workflow_state: WorkflowStateName, status: EventStatus, elapsed_t: Optional[float] = None):

        instance = cls.get()
        if status == EventStatus.FAILURE:
            instance.data.append(ResourceMetadata(time=instance._epoch_time(),
                                                  state=workflow_state, active=-1, failure_t=elapsed_t))
        else:
            instance.data.append(ResourceMetadata(time=instance._epoch_time(),
                                                  state=workflow_state, active=-1, success_t=elapsed_t))

    @classmethod
    def interruption(cls, workflow_state: WorkflowStateName, elapsed_t: float):
        instance = cls.get()
        instance.data.append(ResourceMetadata(time=instance._epoch_time(),
                                              state=workflow_state, interruption_t=elapsed_t))

    @classmethod
    def waiting(cls, workflow_state: WorkflowStateName, waiting_t: float):
        instance = cls.get()
        instance.data.append(ResourceMetadata(time=instance._epoch_time(),
                                              state=workflow_state, waiting_t=waiting_t))

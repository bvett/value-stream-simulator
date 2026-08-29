import uuid
from typing import Optional, Self

from simpy import Environment

from value_stream.core import EventStatus

from .resource_history import ResourceHistory
from .resource_metadata import ResourceMetadata
from .trackable import Trackable


class Tracker:

    _instance: Optional[Self] = None

    @classmethod
    def get(cls) -> Self:
        if cls._instance is None:
            cls._instance = cls()

        return cls._instance

    @classmethod
    def set(cls, instance: Self):
        cls._instance = instance

    def start_epoch(self):
        pass

    def register(self, r: Trackable):
        pass

    def start_work(self, r: Trackable, elapsed_t: float):
        pass

    def complete_work(self, r: Trackable, status: EventStatus, elapsed_t: Optional[float] = None):
        pass

    def interruption(self, r: Trackable, elapsed_t: float):
        pass

    def waiting(self, r: Trackable, waiting_t: float):
        pass


class ResourceTracker(Tracker):

    def __init__(self, env: Environment):
        super().__init__()
        self._env = env
        self.epoch_t: float = 0

    def start_epoch(self):
        self.epoch_t = self._env.now
        ResourceHistory.start_epoch()

    def _epoch_time(self):
        return self._env.now - self.epoch_t

    def register(self, r: Trackable):
        r.tracker_id = uuid.uuid4()
        ResourceHistory.append(ResourceMetadata(time=self._epoch_time(),
                                                state=r.workflow_state, allocated=1))

    def start_work(self, r: Trackable, elapsed_t: float):
        ResourceHistory.append(ResourceMetadata(time=self._epoch_time(),
                                                state=r.workflow_state, active=1, idle_t=elapsed_t))

    def complete_work(self, r: Trackable, status: EventStatus, elapsed_t: Optional[float] = None):

        if status == EventStatus.FAILURE:
            ResourceHistory.append(ResourceMetadata(time=self._epoch_time(),
                                                    state=r.workflow_state, active=-1, failure_t=elapsed_t))
        else:
            ResourceHistory.append(ResourceMetadata(time=self._epoch_time(),
                                                    state=r.workflow_state, active=-1, success_t=elapsed_t))

    def interruption(self, r: Trackable, elapsed_t: float):
        ResourceHistory.append(ResourceMetadata(time=self._epoch_time(),
                                                state=r.workflow_state, interruption_t=elapsed_t))

    def waiting(self, r: Trackable, waiting_t: float):
        ResourceHistory.append(ResourceMetadata(time=self._epoch_time(),
                                                state=r.workflow_state, waiting_t=waiting_t))

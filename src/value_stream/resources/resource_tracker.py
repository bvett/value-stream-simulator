import uuid

from simpy import Environment
from typing import Optional, Self

from value_stream.core import WorkflowStateName

from .trackable import Trackable
from ..event_status import EventStatus


class ResourceHistory:

    def __init__(self,
                 time: float,
                 state: WorkflowStateName,
                 allocated: int = 0,
                 active: int = 0,
                 success_t: Optional[float] = None,
                 failure_t: Optional[float] = None,
                 interruption_t: Optional[float] = None,
                 waiting_t: Optional[float] = None,
                 idle_t: Optional[float] = None):

        self.time = time
        self.state = state
        self.allocated = allocated
        self.active = active
        self.success_t = success_t
        self.failure_t = failure_t
        self.interruption_t = interruption_t
        self.waiting_t = waiting_t
        self.idle_t = idle_t


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

    def __init__(self):
        self.data: list[ResourceHistory] = []

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
        self.data = []

    def _epoch_time(self):
        return self._env.now - self.epoch_t

    def register(self, r: Trackable):
        r.tracker_id = uuid.uuid4()
        self.data.append(ResourceHistory(time=self._epoch_time(),
                         state=r.workflow_state, allocated=1))

    def start_work(self, r: Trackable, elapsed_t: float):
        self.data.append(ResourceHistory(time=self._epoch_time(),
                                         state=r.workflow_state, active=1, idle_t=elapsed_t))

    def complete_work(self, r: Trackable, status: EventStatus, elapsed_t: Optional[float] = None):

        if status == EventStatus.FAILURE:
            self.data.append(ResourceHistory(time=self._epoch_time(),
                                             state=r.workflow_state, active=-1, failure_t=elapsed_t))
        else:
            self.data.append(ResourceHistory(time=self._epoch_time(),
                                             state=r.workflow_state, active=-1, success_t=elapsed_t))

    def interruption(self, r: Trackable, elapsed_t: float):
        self.data.append(ResourceHistory(time=self._epoch_time(),
                         state=r.workflow_state, interruption_t=elapsed_t))

    def waiting(self, r: Trackable, waiting_t: float):
        self.data.append(ResourceHistory(time=self._epoch_time(),
                         state=r.workflow_state, waiting_t=waiting_t))

from typing import Optional, Protocol, runtime_checkable

from simpy import Environment

from value_stream.task import TaskState
from value_stream.task import EventStatus

from .resource_metadata import ResourceMetadata


class ResourceTracker(Protocol):

    @property
    def data(self) -> list[ResourceMetadata]: ...
    def register(self, workflow_state: TaskState) -> None: ...
    def start_work(self, workflow_state: TaskState, elapsed_t: float) -> None: ...
    def complete_work(
        self, workflow_state: TaskState, status: EventStatus, elapsed_t: Optional[float] = None
    ) -> None: ...
    def interruption(self, workflow_state: TaskState, elapsed_t: float) -> None: ...
    def start_waiting(self, workflow_state: TaskState) -> None: ...
    def complete_waiting(self, workflow_state: TaskState, waiting_t: float) -> None: ...


class NoOpResourceTracker:  # pylint: disable=W0613

    @property
    def data(self) -> list[ResourceMetadata]:
        return []

    def register(self, workflow_state: TaskState):
        return

    def start_work(self, workflow_state: TaskState, elapsed_t: float):
        return

    def complete_work(
        self, workflow_state: TaskState, status: EventStatus, elapsed_t: Optional[float] = None
    ):
        return

    def interruption(self, workflow_state: TaskState, elapsed_t: float):
        return

    def start_waiting(self, workflow_state: TaskState):
        return

    def complete_waiting(self, workflow_state: TaskState, waiting_t: float):
        return


class InMemoryResourceTracker:

    def __init__(self, env: Environment):
        self._env = env
        self._epoch_t = env.now
        self._data: list[ResourceMetadata] = []

    @property
    def data(self):
        return self._data.copy()

    def register(self, workflow_state: TaskState):
        self._data.append(
            ResourceMetadata(time=self._env.now - self._epoch_t, state=workflow_state, allocated=1)
        )

    def start_work(self, workflow_state: TaskState, elapsed_t: float):
        self._data.append(
            ResourceMetadata(
                time=self._env.now - self._epoch_t, state=workflow_state, active=1, idle_t=elapsed_t
            )
        )

    def complete_work(
        self, workflow_state: TaskState, status: EventStatus, elapsed_t: Optional[float] = None
    ):

        if status == EventStatus.FAILURE:
            self._data.append(
                ResourceMetadata(
                    time=self._env.now - self._epoch_t,
                    state=workflow_state,
                    active=-1,
                    failure_t=elapsed_t,
                )
            )
        else:
            self._data.append(
                ResourceMetadata(
                    time=self._env.now - self._epoch_t,
                    state=workflow_state,
                    active=-1,
                    success_t=elapsed_t,
                )
            )

    def interruption(self, workflow_state: TaskState, elapsed_t: float):
        self._data.append(
            ResourceMetadata(
                time=self._env.now - self._epoch_t, state=workflow_state, interruption_t=elapsed_t
            )
        )

    def start_waiting(self, workflow_state: TaskState):
        self._data.append(
            ResourceMetadata(time=self._env.now - self._epoch_t, state=workflow_state, waiting=1)
        )

    def complete_waiting(self, workflow_state: TaskState, waiting_t: float):
        self._data.append(
            ResourceMetadata(
                time=self._env.now - self._epoch_t,
                state=workflow_state,
                waiting=-1,
                waiting_t=waiting_t,
            )
        )

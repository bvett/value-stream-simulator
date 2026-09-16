import os
import weakref
from collections.abc import Iterable
from typing import Optional, Type

from tqdm import tqdm

from value_stream.policy import SimulationPolicy
from value_stream.simulation import Model, Simulation, DefaultSimulationPolicy, SimulationResult
from value_stream.task import Task, TaskState

from .web import WebSimulationClient
from .web.local_service import acquire_local_service, release_local_service


class SimulationRunner:

    @classmethod
    def task_states(cls) -> Type[TaskState]:
        return Simulation.task_states

    def __init__(self, service_url: str | None = None):
        configured_url = service_url or os.environ.get("VALUE_STREAM_SERVICE_URL") or None
        self._local_finalizer = None
        if configured_url is None:
            configured_url = acquire_local_service()
            self._local_finalizer = weakref.finalize(self, release_local_service)
        self.client = WebSimulationClient(configured_url)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.client.close()
        if self._local_finalizer is not None:
            self._local_finalizer()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()

    def execute(self, tasks: list[Task],
                models: Iterable[Model],
                pbar: Optional[tqdm] = None,
                policy: SimulationPolicy = DefaultSimulationPolicy(),
                seed: int | None = None) -> list[SimulationResult]:
        """Run the model batch and return results in submission order."""
        if self._closed:
            raise RuntimeError("SimulationRunner is closed")
        if type(policy) is not DefaultSimulationPolicy:
            raise ValueError("version 1 supports only DefaultSimulationPolicy")
        return self.client.execute(tasks=tasks, models=models, pbar=pbar, seed=seed)

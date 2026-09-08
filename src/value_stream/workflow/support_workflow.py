from typing import Optional

from simpy import Environment, Event
from value_stream.task import TaskGenerator
from .workflow_state import WorkflowState


class SupportWorkflow:
    """Generates and assigns tasks to developers outside of the primary SDLC workflow.
    Used to simulate unplanned workload that results in disruption"""

    def __init__(self):

        self._proc = None

        self._signal: Optional[Event] = None

    def start(self, env: Environment,
              generator: TaskGenerator,
              interval: float,
              pending: WorkflowState,
              stop_signal: Optional[Event] = None):

        if stop_signal is None:
            self._signal = env.event()
        else:
            self._signal = stop_signal

        env.process(self._monitor())

        generator.start(env=env,
                        target=pending,
                        interval=interval)

        yield self._signal
        generator.stop()

    def _monitor(self):

        if (self._signal is None) or (self._signal.triggered):
            raise RuntimeError("support workflow has not been started")

        while True:
            yield self._signal
            if (self._proc is not None) and (self._proc.is_alive is True):
                self._proc.interrupt()
            break

    def stop(self):
        if (self._signal is None) or (self._signal.triggered):
            raise RuntimeError("support workflow has not been started")

        self._signal.succeed()

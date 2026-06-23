import itertools
import random
from simpy import Environment, Event, Interrupt

from .assignment_strategy import AssignmentStrategy

from .resources import Developer
from .simulation_policy import SimulationPolicy
from .workflow_state import WorkflowState, TerminalWorkflowState
from .workflow_state_name import WorkflowStateName
from .utils import TaskGenerator


class SupportWorkflow:
    """Generates and assigns tasks to developers outside of the primary SDLC workflow.
    Used to simulate unplanned workload that results in disruption"""

    def __init__(self, env: Environment, policy: SimulationPolicy):
        self.env = env

        self._proc = None

        self.policy = policy

        self._signal: Event | None = None
        self._pending: WorkflowState | None = None
        self._completed: WorkflowState | None = None

    @property
    def pending(self) -> list[Event] | None:
        if not self._pending:
            return None

        return self._pending.items

    @property
    def completed(self) -> list[Event] | None:
        if not self._completed:
            return None

        return self._completed.items

    def start(self, generator: TaskGenerator,
              interval: float,
              developers: list[Developer],
              stop_signal: Event | None = None):

        if stop_signal is None:
            self._signal = self.env.event()
        else:
            self._signal = stop_signal

        if len(developers) == 0:
            raise ValueError("at least one developer must be provided")

        self._pending = WorkflowState(
            self.env, WorkflowStateName.SUPPORT_PENDING)

        self._completed = TerminalWorkflowState(
            self.env, WorkflowStateName.SUPPORT_COMPLETE)

        self.env.process(self._monitor())

        generator.start(env=self.env,
                        target=self._pending,
                        baseline_time=self.env.now,
                        interval=interval)

        self._proc = self.env.process(
            self._processing_loop(developers=developers,
                                  strategy=self.policy.support_strategy(),
                                  source=self._pending,
                                  target=self._completed))

        yield self._proc
        generator.stop()

        return self._completed.items

    def _processing_loop(self,
                         developers: list[Developer],
                         strategy: AssignmentStrategy,
                         source: WorkflowState,
                         target: WorkflowState):

        match strategy:
            case AssignmentStrategy.RANDOM:
                def gen(developers: list[Developer]):
                    while True:
                        yield random.choice(developers)
                support_delegator = gen(developers)

            case AssignmentStrategy.CYCLIC:
                support_delegator = itertools.cycle(developers)
            case _:
                raise ValueError("unsupported strategy")

        while True:

            try:
                task = yield source.get()

                developer = next(support_delegator)

                self.env.process(
                    developer.operate(env=self.env,
                                      tasks=[task],
                                      target=target,
                                      policy=self.policy))
            except Interrupt:
                break

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

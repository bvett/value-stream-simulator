import itertools
import random
from typing import Optional

from simpy import Environment, Event, Interrupt

from value_stream.core import WorkflowStateName
from value_stream.resources import Developer, ResourcePolicy, ResourceTracker
from value_stream.workflow import AssignmentStrategy, WorkflowPolicy, WorkflowState, TerminalWorkflowState

from .utils import TaskGenerator


class SupportWorkflow:
    """Generates and assigns tasks to developers outside of the primary SDLC workflow.
    Used to simulate unplanned workload that results in disruption"""

    def __init__(self, env: Environment, workflow_policy: WorkflowPolicy, resource_policy: ResourcePolicy):
        self.env = env

        self._proc = None

        self._workflow_policy = workflow_policy
        self._resource_policy = resource_policy

        self._signal: Optional[Event] = None
        self._pending: Optional[WorkflowState] = None
        self._completed: Optional[WorkflowState] = None

    @property
    def pending(self) -> Optional[list[Event]]:
        if not self._pending:
            return None

        return self._pending.items

    @property
    def completed(self) -> Optional[list[Event]]:
        if not self._completed:
            return None

        return self._completed.items

    def start(self, generator: TaskGenerator,
              interval: float,
              developers: list[Developer],
              tracker: ResourceTracker,
              stop_signal: Optional[Event] = None):

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
                                  strategy=self._workflow_policy.support_strategy(),
                                  source=self._pending,
                                  target=self._completed,
                                  tracker=tracker))

        yield self._proc
        generator.stop()

        return self._completed.items

    def _processing_loop(self,
                         developers: list[Developer],
                         strategy: AssignmentStrategy,
                         source: WorkflowState,
                         target: WorkflowState,
                         tracker: ResourceTracker):

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
                                      policy=self._resource_policy,
                                      tracker=tracker))
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

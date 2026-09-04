import itertools
import random
from typing import Optional

from simpy import Environment, Event, Interrupt

from value_stream.core import WorkflowStateName
from value_stream.resources import Developer, ResourcePolicy, ResourceTracker
from value_stream.task import Task, TaskGenerator, DefaultRouter, TaskRouterBase

from .assignment_strategy import AssignmentStrategy
from .workflow_policy import WorkflowPolicy
from .workflow_state import WorkflowState, TerminalWorkflowState


class SupportWorkflow:
    """Generates and assigns tasks to developers outside of the primary SDLC workflow.
    Used to simulate unplanned workload that results in disruption"""

    def __init__(self, workflow_policy: WorkflowPolicy, resource_policy: ResourcePolicy):

        self._proc = None

        self._workflow_policy = workflow_policy
        self._resource_policy = resource_policy

        self._signal: Optional[Event] = None
        self._pending: Optional[WorkflowState] = None
        self._completed: Optional[WorkflowState] = None

    @property
    def pending(self) -> Optional[list[Task]]:
        if not self._pending:
            return None

        return self._pending.items

    @property
    def completed(self) -> Optional[list[Task]]:
        if not self._completed:
            return None

        return self._completed.items

    def start(self, env: Environment,
              generator: TaskGenerator,
              interval: float,
              developers: list[Developer],
              tracker: ResourceTracker,
              stop_signal: Optional[Event] = None):

        if stop_signal is None:
            self._signal = env.event()
        else:
            self._signal = stop_signal

        if len(developers) == 0:
            raise ValueError("at least one developer must be provided")

        self._pending = WorkflowState(
            env, WorkflowStateName.SUPPORT_PENDING)

        self._completed = TerminalWorkflowState(
            env, WorkflowStateName.SUPPORT_COMPLETE)

        task_router = DefaultRouter(self._completed)

        env.process(self._monitor())

        generator.start(env=env,
                        target=self._pending,
                        interval=interval)

        self._proc = env.process(
            self._processing_loop(env=env,
                                  developers=developers,
                                  strategy=self._workflow_policy.support_strategy(),
                                  source=self._pending,
                                  task_router=task_router,
                                  tracker=tracker))

        yield self._proc
        generator.stop()

        return self._completed.items

    def _processing_loop(self,
                         env: Environment,
                         developers: list[Developer],
                         strategy: AssignmentStrategy,
                         source: WorkflowState,
                         task_router: TaskRouterBase,
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

                env.process(
                    developer.operate(env=env,
                                      tasks=[task],
                                      workflow_state=WorkflowStateName.DEVELOPMENT,
                                      task_router=task_router,
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

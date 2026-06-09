from enum import Enum
import itertools
import random
from simpy import Environment, Interrupt

from .resources import Developer
from .workflow_state import WorkflowState
from .workflow_state_name import WorkflowStateName
from .utils import TaskGenerator


class SupportWorkflow:
    """Generates and assigns tasks to developers outside of the primary SDLC workflow.
    Used to simulate unplanned workload that results in disruption"""

    class AssignmentStrategy(Enum):
        """Specifies how support work is assigned to a set of developers"""
        RANDOM = 1
        CYCLIC = 2  # round-robin for a more even distribution of workload

    def __init__(self, env: Environment, target: WorkflowState):
        self.env = env

        self.source = WorkflowState(
            self.env, WorkflowStateName.SUPPORT_PENDING)

        self.target = target
        self._proc = None

    def start(self, generator: TaskGenerator, developers: list[Developer],
              strategy: AssignmentStrategy = AssignmentStrategy.RANDOM):

        if len(developers) == 0:
            raise ValueError("at least one developer must be provided")

        generator.start(self.env, self.source)

        self._proc = self.env.process(
            self._processing_loop(developers, strategy))

        yield self._proc

        generator.stop()

    def _processing_loop(self, developers: list[Developer], strategy: AssignmentStrategy):

        match strategy:
            case self.AssignmentStrategy.RANDOM:
                def gen(developers: list[Developer]):
                    while True:
                        yield random.choice(developers)
                support_delegator = gen(developers)

            case self.AssignmentStrategy.CYCLIC:
                support_delegator = itertools.cycle(developers)
            case _:
                raise ValueError("unsupported strategy")

        while True:

            try:
                task = yield self.source.get()

                developer = next(support_delegator)

                self.env.process(
                    developer.operate(self.env, [task], self.target))
            except Interrupt:
                break

    def stop(self):
        if (self._proc is not None) and (self._proc.is_alive is True):
            self._proc.interrupt()

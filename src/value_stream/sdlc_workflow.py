
from simpy import Environment, Event

from .simulation_policy import SimulationPolicy
from .task import Task
from .workflow_state import TerminalWorkflowState, WorkflowState, WorkflowStateName
from .resources import ResourceOperator


class SDLCWorkflow:
    """Controls movement of tasks through the SDLC process

    At initialization, wraps each Task object in a TaskResult and
    adds to the pending queue.   Resources, such as Developer and
    Toolchain, move TaskResult objects between queues while
    updating statistics to reflect processing times.

    SDLC process is: pending->developed->delivered
    """

    def __init__(self, env: Environment, policy: SimulationPolicy | None) -> None:
        """Initializes a workflow with pending tasks"""

        self.env = env

        self.pending = WorkflowState(self.env, WorkflowStateName.PENDING)

        self.developed = WorkflowState(
            self.env, WorkflowStateName.DEV_COMPLETE)

        self.qa_complete = WorkflowState(
            self.env, WorkflowStateName.QA_COMPLETE)

        self.delivered = TerminalWorkflowState(
            self.env, WorkflowStateName.DELIVERY)

        self.policy = policy

    def start(self, tasks: list[Task],
              developer_manager: ResourceOperator,
              qa_manager: ResourceOperator,
              toolchain_manager: ResourceOperator,
              signal: Event):
        """Signals workflow completion when all tasks specified at
        initialization are in the delivered queue"""

        idx = len(self.delivered.items)

        for task in tasks:
            yield self.pending.put(task.reset(self.env.now))

        delivery_target = len(self.pending.items)

        developer_manager.start(
            source=self.pending,
            target=self.developed)

        qa_manager.start(
            source=self.developed,
            target=self.qa_complete,
            target_upon_failure=self.pending)

        toolchain_manager.start(
            source=self.qa_complete,
            target=self.delivered,
            target_upon_failure=self.qa_complete)

        while True:

            if len(self.delivered.items[idx:]) == delivery_target:
                if len(self.pending.items) > 0:
                    raise RuntimeError("Pending should be empty")

                developer_manager.stop()
                qa_manager.stop()
                toolchain_manager.stop()

                yield signal.succeed(self.delivered.items[idx:])

            yield self.env.timeout(1)

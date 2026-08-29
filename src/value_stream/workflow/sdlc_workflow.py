from simpy import Environment, Event

from value_stream.core import WorkflowStateName
from value_stream.resources import ResourceTracker
from value_stream.task import Task

from .resource_operator import ResourceOperator
from .workflow_state import TerminalWorkflowState, WorkflowState


class SDLCWorkflow:
    """Controls movement of tasks through the SDLC process

    At initialization, wraps each Task object in a TaskResult and
    adds to the pending queue.   Resources, such as Developer and
    Toolchain, move TaskResult objects between queues while
    updating statistics to reflect processing times.

    SDLC process is: pending->developed->delivered
    """

    def __init__(self, env: Environment) -> None:
        """Initializes a workflow with pending tasks"""

        self.env = env

        self.pending = WorkflowState(self.env, WorkflowStateName.PENDING)

        self.developed = WorkflowState(
            self.env, WorkflowStateName.DEV_COMPLETE)

        self.qa_complete = WorkflowState(
            self.env, WorkflowStateName.QA_COMPLETE)

        self.delivered = TerminalWorkflowState(
            self.env, WorkflowStateName.DELIVERY)

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

        ResourceTracker.start_epoch()
        # resource_tracker.start.epoch(env)

        delivery_target = len(self.pending.items)

        self.delivered.set_alarm(
            limit=idx + delivery_target, signal=signal)

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

        yield signal

        developer_manager.stop()
        qa_manager.stop()
        toolchain_manager.stop()

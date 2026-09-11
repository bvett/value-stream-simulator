from simpy import Environment, Event

from value_stream.task import Task, TypeRouter, StatusRouter, TaskState

from .resource_operator import ResourceOperator
from .task_store import TerminalTaskStore, TaskStore


class SDLCWorkflow:
    """Controls movement of tasks through the SDLC process

    At initialization, wraps each Task object in a TaskResult and
    adds to the pending queue.   Resources, such as Developer and
    Toolchain, move TaskResult objects between queues while
    updating statistics to reflect processing times.

    SDLC process is: pending->developed->delivered
    """

    class WorkflowState(TaskState):
        PENDING = "pending"
        DEVELOPMENT = "development"
        DEV_COMPLETE = "dev_complete"
        QA_TESTING = "qa_testing"
        QA_COMPLETE = "qa_complete"
        DEPLOYMENT = "deployment"
        DELIVERY = "delivery"
        SUPPORT_PENDING = "support_pending"
        SUPPORT_COMPLETE = "support_complete"

    def __init__(self) -> None:
        """Initializes a workflow with pending tasks"""

    def start(self, env: Environment,
              tasks: list[Task],
              developer_manager: ResourceOperator,
              qa_manager: ResourceOperator,
              toolchain_manager: ResourceOperator,
              signal: Event,
              pending: TaskStore):
        """Signals workflow completion when all tasks specified at
        initialization are in the delivered queue"""

        developed = TaskStore(
            env, SDLCWorkflow.WorkflowState.DEV_COMPLETE)

        qa_complete = TaskStore(
            env, SDLCWorkflow.WorkflowState.QA_COMPLETE)

        delivered = TerminalTaskStore(
            env, SDLCWorkflow.WorkflowState.DELIVERY)

        support_completed = TerminalTaskStore(
            env, SDLCWorkflow.WorkflowState.SUPPORT_COMPLETE)

        for task in tasks:
            yield pending.put(task)

        delivered.set_alarm(
            limit=len(pending.items), signal=signal)

        developer_manager.start(
            source=pending,
            workflow_state=SDLCWorkflow.WorkflowState.DEVELOPMENT,
            task_router=TypeRouter(on_development=developed, on_support=support_completed))

        qa_manager.start(
            source=developed,
            workflow_state=SDLCWorkflow.WorkflowState.QA_TESTING,
            task_router=StatusRouter(on_success=qa_complete, on_failure=pending))

        toolchain_manager.start(
            source=qa_complete,
            workflow_state=SDLCWorkflow.WorkflowState.DEPLOYMENT,
            task_router=StatusRouter(on_success=delivered, on_failure=qa_complete))

        yield signal

        developer_manager.stop()
        qa_manager.stop()
        toolchain_manager.stop()

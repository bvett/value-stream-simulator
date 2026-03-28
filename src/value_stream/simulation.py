import logging
from typing import Iterable

from simpy import Environment, Event
from tqdm import tqdm

from .managers import DeveloperManager, QAManager, ToolchainManager
from .model import Model
from .simulation_result import SimulationResult
from .task import Task
from .workflow_state import WorkflowState, TerminalWorkflowState
from .workflow_state_name import WorkflowStateName

logger = logging.getLogger(__name__)


class Simulation:
    """Simulates software delivery given a set of tasks and parameters.

    Simulation runs a set of Task objects through a workflow that
    represents the software development lifecycle (SDLC).  The time it
    takes for a task to complete the workflow is determined by the
    attributes of a Model, and this affects its depreciated value
    at the time of delivery.
    """

    def execute(self, tasks: list[Task],
                models: Iterable[Model],
                pbar: tqdm | None = None) -> list[SimulationResult]:
        """Executes a simulation.

        Args:
            tasks (list[Task]): Development tasks.
            models (Iterable[Model]): Model(s) containing attributes for controlling a simulation.
            pbar (tqdm | None, optional): Optional progress bar.
            Defaults to None.

        Returns:
            list[ModelResult]: Set of simulation outcomes, one per Model.
        """

        simulation_results: list[SimulationResult] = []

        for model in models:

            env = Environment()

            developer_manager = DeveloperManager(
                env, model.developer_team)

            qa_manager = QAManager(env, concurrency=model.num_qa_resources)

            toolchain_manager = ToolchainManager(env, deployment_duration=model.deployment_duration,
                                                 deployment_cadence=model.deployment_cadence,
                                                 concurrency=model.toolchain_concurrency)

            workflow = self.Workflow(env)

            env.process(workflow.start(
                tasks=tasks,
                developer_manager=developer_manager,
                qa_manager=qa_manager,
                toolchain_manager=toolchain_manager))

            delivered_tasks: list[Task] = env.run(
                workflow.is_complete())  # type: ignore

            for task in delivered_tasks:
                simulation_results.append(SimulationResult(
                    model, task, task.history.events))

            if pbar:
                pbar.update()

        return simulation_results

    class Workflow:
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

            # Signal for when workflow is complete
            self._completion_semaphore = env.event()

        def start(self, tasks: list[Task],
                  developer_manager: DeveloperManager,
                  qa_manager: QAManager,
                  toolchain_manager: ToolchainManager):
            """Signals workflow completion when all tasks specified at
            initialization are in the delivered queue"""

            pending = WorkflowState(self.env, WorkflowStateName.PENDING)
            for task in tasks:
                pending.put(task.reset())

            delivery_target = len(pending.items)

            developed = WorkflowState(self.env, WorkflowStateName.DEV_COMPLETE)

            qa_complete = WorkflowState(
                self.env, WorkflowStateName.QA_COMPLETE)

            delivered = TerminalWorkflowState(
                self.env, WorkflowStateName.DELIVERY)

            developer_manager.start(
                source=pending,
                target=developed)

            qa_manager.start(
                source=developed,
                target=qa_complete
            )

            toolchain_manager.start(
                source=qa_complete,
                target=delivered)

            while True:
                yield self.env.timeout(1)

                if len(delivered.items) == delivery_target:
                    self._completion_semaphore.succeed(delivered.items)

        def is_complete(self) -> Event:
            """Returns the event used to signal completion"""
            return self._completion_semaphore

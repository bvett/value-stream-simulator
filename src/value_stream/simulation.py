import logging
from typing import Iterable

from simpy import Environment, Event
from tqdm import tqdm

from .managers import DeveloperManager, QAManager, ToolchainManager
from .model import Model
from .resources import QATester, Toolchain
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

        env = Environment()
        workflow = self.Workflow(env)

        for model in models:

            developer_manager = DeveloperManager(
                env, model.developer_team)

            qa_manager = QAManager(env, QATester.create(
                limit=model.num_qa_resources))

            toolchain_manager = ToolchainManager(env, Toolchain.create(model.deployment_duration, limit=model.toolchain_concurrency),
                                                 deployment_cadence=model.deployment_cadence)
            signal = env.event()
            env.process(workflow.start(
                tasks=tasks,
                developer_manager=developer_manager,
                qa_manager=qa_manager,
                toolchain_manager=toolchain_manager,
                signal=signal))

            delivered_tasks: list[Task] = env.run(
                until=signal)  # type:ignore

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

            self.pending = WorkflowState(self.env, WorkflowStateName.PENDING)

            self.developed = WorkflowState(
                self.env, WorkflowStateName.DEV_COMPLETE)

            self.qa_complete = WorkflowState(
                self.env, WorkflowStateName.QA_COMPLETE)

            self.delivered = TerminalWorkflowState(
                self.env, WorkflowStateName.DELIVERY)

        def start(self, tasks: list[Task],
                  developer_manager: DeveloperManager,
                  qa_manager: QAManager,
                  toolchain_manager: ToolchainManager,
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
                target=self.qa_complete)

            toolchain_manager.start(
                source=self.qa_complete,
                target=self.delivered)

            while True:

                if len(self.delivered.items[idx:]) == delivery_target:
                    if len(self.pending.items) > 0:
                        raise RuntimeError("Pending should be empty")

                    developer_manager.stop()
                    qa_manager.stop()
                    toolchain_manager.stop()

                    yield signal.succeed(self.delivered.items[idx:])

                    break

                yield self.env.timeout(1)

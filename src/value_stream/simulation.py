import logging
from typing import Iterable

from simpy import Environment
from tqdm import tqdm

from .resources import ResourceOperator
from .model import Model
from .sdlc_workflow import SDLCWorkflow
from .simulation_policy import SimulationPolicy, DefaultSimulationPolicy
from .simulation_result import SimulationResult
from .support_workflow import SupportWorkflow
from .task import Task
from .utils import TaskGenerator
from .workflow_state import TerminalWorkflowState
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
                support_generator: TaskGenerator | None = None,
                pbar: tqdm | None = None,
                policy: SimulationPolicy = DefaultSimulationPolicy()) -> list[SimulationResult]:
        """Executes a simulation.

        Args:
            tasks (list[Task]): Development tasks.
            models (Iterable[Model]): Model(s) containing attributes for controlling a simulation.
            pbar (tqdm | None, optional): Optional progress bar.
            Defaults to None.

        Returns:
            list[SimulationResult]: Set of simulation outcomes, one per Model.
        """

        simulation_results: list[SimulationResult] = []

        env = Environment()
        workflow = SDLCWorkflow(env, policy=policy)
        support_target = TerminalWorkflowState(
            env, WorkflowStateName.SUPPORT_COMPLETE)
        support_workflow = SupportWorkflow(env, support_target, policy=policy)

        for model in models:

            developer_manager = ResourceOperator(
                env, model.developer_team,
                policy=policy)

            qa_manager = ResourceOperator(env, model.qa_testers, policy=policy)

            toolchain_manager = ResourceOperator(
                env, model.toolchain_pool, policy=policy, cadence=model.deployment_cadence)

            signal = env.event()
            env.process(workflow.start(
                tasks=tasks,
                developer_manager=developer_manager,
                qa_manager=qa_manager,
                toolchain_manager=toolchain_manager,
                signal=signal))

            if support_generator is not None:
                env.process(support_workflow.start(
                    generator=support_generator,
                    developers=list(model.developer_team)))

            delivered_tasks = env.run(
                until=signal)  # type:ignore

            if support_generator is not None:
                support_workflow.stop()

            if delivered_tasks is not None:
                for task in delivered_tasks:
                    simulation_results.append(SimulationResult(
                        model, task, task.history.events))

            for task in support_target.items:
                simulation_results.append(SimulationResult(
                    model, task, task.history.events))

            if pbar:
                pbar.update()

        return simulation_results

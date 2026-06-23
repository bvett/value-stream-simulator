import logging
from typing import Iterable

from simpy import Environment, Event, Process
from simpy.events import AllOf
from tqdm import tqdm

from .resources import ResourceOperator
from .model import Model
from .sdlc_workflow import SDLCWorkflow
from .simulation_policy import SimulationPolicy, DefaultSimulationPolicy
from .simulation_result import SimulationResult
from .support_workflow import SupportWorkflow
from .task import Task
from .utils import TaskGenerator

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
        sdlc_workflow = SDLCWorkflow(env, policy=policy)
        support_workflow = SupportWorkflow(env, policy=policy)

        for model in models:
            developer_manager = ResourceOperator(
                env, model.developer_team,
                policy=policy)

            qa_manager = ResourceOperator(env, model.qa_testers, policy=policy)

            toolchain_manager = ResourceOperator(
                env, model.toolchain_pool, policy=policy, cadence=model.deployment_cadence)

            delivery_complete = env.event()
            support_workflow_p: Process | None = None

            sim_termination_events = [delivery_complete]

            env.process(sdlc_workflow.start(
                tasks=tasks,
                developer_manager=developer_manager,
                qa_manager=qa_manager,
                toolchain_manager=toolchain_manager,
                signal=delivery_complete))

            if (support_generator is not None) and (model.support_interval is not None):
                support_workflow_p = env.process(support_workflow.start(
                    generator=support_generator,
                    interval=model.support_interval,
                    developers=list(model.developer_team),
                    stop_signal=delivery_complete))
                sim_termination_events.append(support_workflow_p)

            completed_tasks = env.run(
                until=AllOf(env, sim_termination_events))  # type:ignore

            if completed_tasks is None:
                raise RuntimeError("unrecoverable simulation error")

            simulation_results.extend(
                self._process_results(model, completed_tasks))

            if pbar:
                pbar.update()

        return simulation_results

    def _process_results(self, model: Model, completed_tasks: dict[Event, list[Task]]):
        result: list[SimulationResult] = []

        for tasks in completed_tasks.values():
            for task in tasks:
                result.append(SimulationResult(
                    model, task, task.history.events))

        return result

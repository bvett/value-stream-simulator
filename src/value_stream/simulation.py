import copy
import logging
from typing import Iterable

from tqdm import tqdm
from simpy import Environment, Event, Store

from .simulation_result import SimulationResult
from .developer import DeveloperTeam
from .model import Model
from .task import Task
from .toolchain import Toolchain

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

        model_results: list[SimulationResult] = []

        for model in models:

            env = Environment()

            developer_team = DeveloperTeam(
                env, model.developer_team)

            toolchain = Toolchain(
                env, concurrency=model.toolchain_concurrency,
                deployment_duration=model.deployment_duration,
                deployment_cadence=model.deployment_cadence)

            workflow = self.Workflow(env)

            env.process(workflow.start(
                tasks=tasks,
                developer_team=developer_team,
                toolchain=toolchain))

            delivered_tasks: list[Task] = env.run(
                workflow.is_complete())  # type: ignore

            model_results.append(SimulationResult(
                model, delivered_tasks))

            if pbar:
                pbar.update()

        return model_results

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
                  developer_team: DeveloperTeam,
                  toolchain: Toolchain):
            """Signals workflow completion when all tasks specified at
            initialization are in the delivered queue"""

            pending = Store(self.env)
            for task in tasks:
                pending.put(copy.deepcopy(task))

            delivery_target = len(pending.items)

            developed = Store(self.env)
            delivered = Store(self.env)

            self.env.process(developer_team.start(
                source=pending,
                target=developed))

            self.env.process(toolchain.start(
                source=developed,
                target=delivered))

            while True:
                yield self.env.timeout(1)

                if len(delivered.items) == delivery_target:
                    self._completion_semaphore.succeed(delivered.items)

        def is_complete(self) -> Event:
            """Returns the event used to signal completion"""
            return self._completion_semaphore

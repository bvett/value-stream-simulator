import logging
from typing import Iterable, Optional

from tqdm import tqdm

from value_stream.simulation import Model, Simulation, SimulationPolicy, \
    DefaultSimulationPolicy, SimulationResult
from value_stream.task import Task, TaskGenerator


logger = logging.getLogger(__name__)


class SimulationRunner:
    def __init__(self):
        self.client: Simulation = Simulation()

    def execute(self, tasks: list[Task],
                models: Iterable[Model],
                support_generator: Optional[TaskGenerator] = None,
                pbar: Optional[tqdm] = None,
                policy: SimulationPolicy = DefaultSimulationPolicy()) -> list[SimulationResult]:
        """Executes a simulation.

        Args:
            tasks (list[Task]): Development tasks.
            models (Iterable[Model]): Model(s) containing attributes for controlling a simulation.
            pbar (Optional[tqdm], optional): Optional progress bar.
            Defaults to None.

        Returns:
            list[SimulationResult]: Set of simulation outcomes, one per Model.
        """

        results: list[SimulationResult] = []

        for model in models:

            results.append(self.client.execute(
                model=model,
                tasks=tasks,
                policy=policy,
                support_generator=support_generator))

            if pbar:
                pbar.update()

        return results

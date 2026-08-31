import logging
from typing import Iterable, Optional

from simpy import Environment
from tqdm import tqdm

from value_stream.simulation import Model, Simulation, SimulationPolicy, \
    DefaultSimulationPolicy, SimulationResult
from value_stream.task import Task, TaskGenerator
from value_stream.workflow import SDLCWorkflow, SupportWorkflow


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

        env = Environment()
        sdlc_workflow = SDLCWorkflow(env)
        support_workflow = SupportWorkflow(
            env, resource_policy=policy, workflow_policy=policy)

        for model in models:

            results.append(self.client.execute(
                env=env,
                model=model,
                tasks=Task.start_epoch(tasks, env),
                policy=policy,
                sdlc_workflow=sdlc_workflow,
                support_generator=support_generator,
                support_workflow=support_workflow))

            if pbar:
                pbar.update()

        return results

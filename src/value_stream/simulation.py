import logging
from typing import Iterable, Optional

from simpy import Environment, Event, Process
from simpy.events import AllOf
from tqdm import tqdm

from value_stream.task import Task, TaskEvent
from value_stream.resources import ResourceTracker, Tracker
from value_stream.workflow import ResourceOperator, SDLCWorkflow


from .model import Model
from .simulation_metadata import SimulationMetadata
from .simulation_policy import SimulationPolicy, DefaultSimulationPolicy
from .simulation_result import SimulationResult, SummaryResult
from .support_workflow import SupportWorkflow
from .utils import TaskGenerator

logger = logging.getLogger(__name__)


class Simulation:
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
        Tracker.set(ResourceTracker(env))
        sdlc_workflow = SDLCWorkflow(env)
        support_workflow = SupportWorkflow(
            env, resource_policy=policy, workflow_policy=policy)

        for model in models:

            results.append(self._execute_inner(
                env=env,
                model=model,
                tasks=tasks,
                policy=policy,
                sdlc_workflow=sdlc_workflow,
                support_generator=support_generator,
                support_workflow=support_workflow))

            if pbar:
                pbar.update()

        return results

    def _execute_inner(self, env: Environment,
                       model: Model,
                       tasks: list[Task],
                       policy: SimulationPolicy,
                       sdlc_workflow: SDLCWorkflow,
                       support_workflow: SupportWorkflow,
                       support_generator: Optional[TaskGenerator] = None) -> SimulationResult:
        developer_manager = ResourceOperator(
            env, model.developer_team,
            policy=policy)

        qa_manager = ResourceOperator(env, model.qa_testers, policy=policy)

        toolchain_manager = ResourceOperator(
            env, model.toolchain_pool, policy=policy, cadence=model.deployment_cadence)

        delivery_complete = env.event()
        support_workflow_p: Optional[Process] = None

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

        start_t = env.now

        completed_tasks = env.run(
            until=AllOf(env, sim_termination_events))  # type:ignore

        sim_duration = env.now - start_t

        if completed_tasks is None:
            raise RuntimeError("unrecoverable simulation error")

        summary_result, task_events = self._process_results(
            model=model, completed_tasks=completed_tasks, sim_duration=sim_duration)

        return SimulationResult(summary_result=summary_result,
                                metadata=SimulationMetadata(model=model,
                                                            resource_metadata=Tracker.get().data,
                                                            event_metadata=task_events))

    def _process_results(self, model: Model,
                         completed_tasks: dict[Event, list[Task]],
                         sim_duration: float) -> tuple[SummaryResult, list[TaskEvent]]:

        total_initial_value = 0
        total_delivered_value = 0

        task_events: list[TaskEvent] = []

        for tasks in completed_tasks.values():
            for task in tasks:
                total_initial_value += task.value()
                total_delivered_value += task.delivered_value
                task_events.extend(task.history.events)

        if total_initial_value == 0:
            raise ValueError("")

        summary_result = SummaryResult(model=model,
                                       completion_time=sim_duration,
                                       total_delivered_value=total_delivered_value,
                                       loss=(total_delivered_value-total_initial_value) / total_initial_value)

        return summary_result, task_events

import logging
from typing import Dict, Iterable, Optional

from simpy import Environment, Event, Process
from simpy.events import AllOf
from tqdm import tqdm

from .resources import ResourceOperator
from .model import Model
from .sdlc_workflow import SDLCWorkflow
from .simulation_policy import SimulationPolicy, DefaultSimulationPolicy
from .simulation_result import SimulationResultV2, SummaryResult, TimelineResult
from .support_workflow import SupportWorkflow
from .task import Task
from .task_event import TaskEvent
from .utils import TaskGenerator
from .workflow_state_name import WorkflowStateName

logger = logging.getLogger(__name__)


class SimulationV2:
    def execute(self, tasks: list[Task],
                models: Iterable[Model],
                support_generator: Optional[TaskGenerator] = None,
                pbar: Optional[tqdm] = None,
                policy: SimulationPolicy = DefaultSimulationPolicy()) -> list[SimulationResultV2]:
        """Executes a simulation.

        Args:
            tasks (list[Task]): Development tasks.
            models (Iterable[Model]): Model(s) containing attributes for controlling a simulation.
            pbar (Optional[tqdm], optional): Optional progress bar.
            Defaults to None.

        Returns:
            list[SimulationResult]: Set of simulation outcomes, one per Model.
        """

        results: list[SimulationResultV2] = []

        env = Environment()
        sdlc_workflow = SDLCWorkflow(env, policy=policy)
        support_workflow = SupportWorkflow(env, policy=policy)

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
                       support_generator: Optional[TaskGenerator] = None) -> SimulationResultV2:
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

        # This needs to return list[SimulationResult] and list[SimulationMetadata]

        return SimulationResultV2(summary_result=self._create_summary_result(model=model,
                                                                             completed_tasks=completed_tasks,
                                                                             sim_duration=sim_duration))  # ,
        # detailed_result=self._create_timeline_results(model=model,
        #                                               completed_tasks=completed_tasks))

    def _create_summary_result(self, model: Model,
                               completed_tasks: dict[Event, list[Task]],
                               sim_duration: float) -> SummaryResult:

        total_initial_value = 0
        total_delivered_value = 0

        for tasks in completed_tasks.values():
            for task in tasks:
                total_initial_value += task.value()
                total_delivered_value += task.delivered_value

        if total_initial_value == 0:
            raise ValueError("")

        return SummaryResult(model=model,
                             completion_time=sim_duration,
                             total_delivered_value=total_delivered_value,
                             loss=(total_delivered_value-total_initial_value) / total_initial_value)

    def _create_timeline_results(self, model: Model, completed_tasks: dict[Event, list[Task]]) -> list[TimelineResult]:

        result: list[TimelineResult] = []

        for tasks in completed_tasks.values():
            for task in tasks:

                start_times: Dict[WorkflowStateName, float] = {}

                for event in task.history.events:
                    if event.event_type == TaskEvent.EventType.START:
                        start_times[event.event] = event.time
                        continue

                    if event.event_type == TaskEvent.EventType.END:
                        start_time = start_times.pop(event.event, None)

                        if start_time is None:
                            raise RuntimeError(
                                "Unable to determine start time for event")

                    elif event.event_type == TaskEvent.EventType.TERMINAL:
                        start_time = event.time

                    else:
                        raise RuntimeError("Unknown EventType")

                    present_value = task.value(event.time)
                    initial_value = task.value()
                    loss = 0 if initial_value == 0 else (
                        present_value - initial_value) / initial_value

                    r = TimelineResult(model=model,
                                       time=start_time,
                                       duration=event.time - start_time,
                                       workflow_state=event.event,
                                       value=present_value,
                                       loss=loss,
                                       status=event.status)

                    result.append(r)

        return result

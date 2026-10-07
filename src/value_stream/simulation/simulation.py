import logging

from simpy import Environment, Event
from simpy.events import AllOf


from value_stream.policy import SimulationPolicy
from value_stream.resources import InMemoryResourceTracker
from value_stream.task import Task, TaskEvent
from value_stream.workflow import ResourceOperator, SDLCWorkflow, SupportWorkflow, TaskStore

from .model import Model
from .simulation_metadata import SimulationMetadata
from .simulation_result import SimulationResult, SummaryResult

logger = logging.getLogger(__name__)


class Simulation:
    """Runs a model against a task set and collects results."""

    task_states = SDLCWorkflow.WorkflowState

    def execute(
        self, model: Model, tasks: list[Task], policy: SimulationPolicy
    ) -> SimulationResult:
        """Execute the requested simulation operation.

        Args:
            model (Model): Model configuration for the simulation.
            tasks (list[Task]): Tasks to process.
            policy (SimulationPolicy): Policy used to make simulation decisions.

        Returns:
            SimulationResult: SimulationResult containing the completed run metrics and task history.
        """
        env = Environment()

        pending = TaskStore(env, SDLCWorkflow.WorkflowState.PENDING)

        sdlc_workflow = SDLCWorkflow()
        support_workflow = SupportWorkflow(story_points=model.support_task_story_points)
        tracker = InMemoryResourceTracker(env)

        developer_manager = ResourceOperator(
            env,
            model.developer_team,
            workflow_policy=policy,
            resource_policy=policy,
            tracker=tracker,
        )

        qa_manager = ResourceOperator(
            env, model.qa_testers, workflow_policy=policy, resource_policy=policy, tracker=tracker
        )

        toolchain_manager = ResourceOperator(
            env,
            model.toolchain_pool,
            workflow_policy=policy,
            resource_policy=policy,
            cadence=model.deployment_cadence,
            tracker=tracker,
        )

        delivery_complete = env.event()

        env.process(
            sdlc_workflow.start(
                env=env,
                tasks=Task.start_epoch(tasks, env),
                developer_manager=developer_manager,
                qa_manager=qa_manager,
                toolchain_manager=toolchain_manager,
                signal=delivery_complete,
                pending=pending,
            )
        )

        if model.support_interval is not None:

            support_workflow.start(env=env, interval=model.support_interval, target=pending)

        start_t = env.now

        completed_tasks: dict[Event, list[Task]] = env.run(
            until=AllOf(env, [delivery_complete])
        )  # pyright: ignore[reportAssignmentType]

        sim_duration = env.now - start_t

        # completed_tasks is always expected to have a value.  A ValueError is raised otherwise

        summary_result, task_events = self._process_results(
            model=model, completed_tasks=completed_tasks, sim_duration=sim_duration
        )

        return SimulationResult(
            summary_result=summary_result,
            metadata=SimulationMetadata(
                model=model, resource_metadata=tracker.data, event_metadata=task_events
            ),
        )

    def _process_results(
        self, model: Model, completed_tasks: dict[Event, list[Task]], sim_duration: float
    ) -> tuple[SummaryResult, list[TaskEvent]]:
        """Collect task and resource metrics from the completed simulation.

        Args:
            model (Model): Model configuration for the simulation.
            completed_tasks (dict[Event, list[Task]]): Completed tasks grouped by their final event.
            sim_duration (float): Elapsed simulation time.

        Returns:
            tuple[SummaryResult, list[TaskEvent]]: Summary metrics, task events, and resource activity for the completed run.
        """
        total_initial_value = 0
        total_delivered_value = 0

        task_events: list[TaskEvent] = []

        for tasks in completed_tasks.values():
            for task in tasks:
                total_initial_value += task.value()

                if task.history.delivered_value is not None:
                    total_delivered_value += task.history.delivered_value

                task_events.extend(task.history.events)

        if total_initial_value == 0:
            loss = 0
        else:
            loss = (total_delivered_value - total_initial_value) / total_initial_value

        summary_result = SummaryResult(
            model=model,
            completion_time=sim_duration,
            total_delivered_value=total_delivered_value,
            loss=loss,
        )

        return summary_result, task_events

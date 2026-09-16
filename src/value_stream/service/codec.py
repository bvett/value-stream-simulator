"""Explicit adapters between simulation objects and the public JSON contract."""

from collections.abc import Iterable

from value_stream.resources import Developer, QATester, ResourceMetadata, Toolchain
from value_stream.resources.resource_pool import ResourcePool
from value_stream.simulation import (
    Model,
    SimulationMetadata,
    SimulationResult,
    SummaryResult,
)
from value_stream.task import EventStatus, Task, TaskEvent, TaskType
from value_stream.workflow.sdlc_workflow import SDLCWorkflow

from .schemas import (
    DeveloperInput,
    JobRequest,
    MetadataData,
    ModelInput,
    QAInput,
    QAListInput,
    QAPoolInput,
    ResourceMetadataData,
    ResultData,
    SummaryData,
    TaskEventData,
    TaskInput,
    ToolchainInput,
    ToolchainListInput,
    ToolchainPoolInput,
)


def _qa_input(resource: QATester) -> QAInput:
    if type(resource) is not QATester:
        raise ValueError("only QATester resources are supported")
    return QAInput(
        time_cost=resource.time_cost,
        failure_rate=resource.failure_rate,
        failure_cost=resource.failure_cost,
    )


def _toolchain_input(resource: Toolchain) -> ToolchainInput:
    if type(resource) is not Toolchain:
        raise ValueError("only Toolchain resources are supported")
    return ToolchainInput(
        deployment_duration=resource.deployment_duration,
        failure_rate=resource.failure_rate,
    )


def _qa_collection(resources: Iterable[QATester]) -> QAPoolInput | QAListInput:
    if isinstance(resources, ResourcePool):
        if resources._class is not QATester or resources.limit is None:
            raise ValueError("QA pool must be finite and contain QATester")
        return QAPoolInput(limit=resources.limit, **resources.kwargs)
    return QAListInput(resources=[_qa_input(r) for r in resources])


def _toolchain_collection(
    resources: Iterable[Toolchain],
) -> ToolchainPoolInput | ToolchainListInput:
    if isinstance(resources, ResourcePool):
        if resources._class is not Toolchain or resources.limit is None:
            raise ValueError("toolchain pool must be finite and contain Toolchain")
        return ToolchainPoolInput(limit=resources.limit, **resources.kwargs)
    return ToolchainListInput(resources=[_toolchain_input(r) for r in resources])


def encode_model(model: Model) -> ModelInput:
    if type(model) is not Model:
        raise ValueError("only Model is supported in version 1")
    developers = []
    for developer in model.developer_team:
        if type(developer) is not Developer:
            raise ValueError("only Developer resources are supported")
        developers.append(DeveloperInput(name=developer.name, efficiency=developer.efficiency))
    return ModelInput(
        developer_team=developers,
        deployment_cadence=model.deployment_cadence,
        qa_testers=_qa_collection(model.qa_testers),
        toolchain_pool=_toolchain_collection(model.toolchain_pool),
        support_interval=model.support_interval,
        support_task_story_points=model.support_task_story_points,
    )


def encode_request(tasks: list[Task], models: list[Model], seed: int | None) -> JobRequest:
    task_inputs = []
    for task in tasks:
        if type(task) is not Task:
            raise ValueError("only Task is supported in version 1")
        task_inputs.append(
            TaskInput(
                initial_value=task.value(),
                story_points=task.story_points,
                depreciation_rate=task.depreciation_rate,
                task_name=task.task_name,
                creation_sim_t=task.creation_sim_t,
                task_type=task.task_type.value,
            )
        )
    return JobRequest(tasks=task_inputs, models=[encode_model(m) for m in models], seed=seed)


def decode_tasks(inputs: list[TaskInput]) -> list[Task]:
    return [
        Task(
            initial_value=t.initial_value,
            story_points=t.story_points,
            depreciation_rate=t.depreciation_rate,
            task_name=t.task_name,
            creation_sim_t=t.creation_sim_t,
            task_type=TaskType(t.task_type),
        )
        for t in inputs
    ]


def decode_model(input_model: ModelInput) -> Model:
    qa = input_model.qa_testers
    toolchain = input_model.toolchain_pool
    if isinstance(qa, QAPoolInput):
        qa_resources = QATester.create_pool(
            limit=qa.limit,
            time_cost=qa.time_cost,
            failure_rate=qa.failure_rate,
            failure_cost=qa.failure_cost,
        )
    else:
        qa_resources = [QATester(**r.model_dump()) for r in qa.resources]
    if isinstance(toolchain, ToolchainPoolInput):
        toolchain_resources = Toolchain.create_pool(
            limit=toolchain.limit,
            deployment_duration=toolchain.deployment_duration,
            failure_rate=toolchain.failure_rate,
        )
    else:
        toolchain_resources = [Toolchain(**r.model_dump()) for r in toolchain.resources]
    return Model(
        developer_team=[Developer(**d.model_dump()) for d in input_model.developer_team],
        deployment_cadence=input_model.deployment_cadence,
        qa_testers=qa_resources,
        toolchain_pool=toolchain_resources,
        support_interval=input_model.support_interval,
        support_task_story_points=input_model.support_task_story_points,
    )


def encode_result(result: SimulationResult, model_index: int) -> ResultData:
    events = [
        TaskEventData(
            event=e.event.value,
            event_type=e.event_type.value,
            time=e.time,
            status=e.status.value,
            loss=e.loss,
            task_type=e.task_type.value,
            is_rework=e.is_rework,
            duration=e.duration,
            resource_id=e.resource_id,
        )
        for e in result.metadata.event_metadata
    ]
    resources = [
        ResourceMetadataData(
            time=r.time,
            state=r.state.value,
            waiting=r.waiting,
            allocated=r.allocated,
            active=r.active,
            success_t=r.success_t,
            failure_t=r.failure_t,
            interruption_t=r.interruption_t,
            waiting_t=r.waiting_t,
            idle_t=r.idle_t,
        )
        for r in result.metadata.resource_metadata
    ]
    summary = result.summary_result
    return ResultData(
        model_index=model_index,
        model=encode_model(summary.model),
        summary_result=SummaryData(
            completion_time=summary.completion_time,
            total_delivered_value=summary.total_delivered_value,
            loss=summary.loss,
        ),
        metadata=MetadataData(event_metadata=events, resource_metadata=resources),
    )


def decode_result(data: ResultData, original_model: Model) -> SimulationResult:
    state_enum = SDLCWorkflow.WorkflowState
    events = [
        TaskEvent(
            event=state_enum(e.event),
            event_type=TaskEvent.EventType(e.event_type),
            time=e.time,
            status=EventStatus(e.status),
            task_type=TaskType(e.task_type),
            is_rework=e.is_rework,
            duration=e.duration,
            loss=e.loss,
            resource_id=e.resource_id,
        )
        for e in data.metadata.event_metadata
    ]
    resources = [
        ResourceMetadata(
            time=r.time,
            state=state_enum(r.state),
            waiting=r.waiting,
            allocated=r.allocated,
            active=r.active,
            success_t=r.success_t,
            failure_t=r.failure_t,
            interruption_t=r.interruption_t,
            waiting_t=r.waiting_t,
            idle_t=r.idle_t,
        )
        for r in data.metadata.resource_metadata
    ]
    summary = SummaryResult(
        model=original_model,
        completion_time=data.summary_result.completion_time,
        total_delivered_value=data.summary_result.total_delivered_value,
        loss=data.summary_result.loss,
    )
    metadata = SimulationMetadata(
        model=original_model, resource_metadata=resources, event_metadata=events
    )
    return SimulationResult(summary_result=summary, metadata=metadata)

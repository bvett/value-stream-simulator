"""Versioned browser/application wire contract."""

from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import ConfigDict, Field, FiniteFloat, model_validator
from value_stream.service.schemas import (
    WireModel, 
    ModelInput, 
    TaskInput, 
    ErrorEnvelope,
    Status)

GENERATOR_VERSION = "1"
ENGINE_VERSION = "value-stream-app-1"


class AppModel(WireModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )


class ConstantValue(AppModel):
    kind: Literal["constant"] = "constant"
    value: FiniteFloat = Field(default=1, ge=0)


class UniformValue(AppModel):
    kind: Literal["uniform"] = "uniform"
    minimum: FiniteFloat = Field(ge=0)
    maximum: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


ValueSpec = Annotated[ConstantValue | UniformValue, Field(discriminator="kind")]


class TaskSetSpec(AppModel):
    name: str = Field(default="Task set", min_length=1, max_length=120)
    count: int = Field(default=500, gt=0)
    story_points: ValueSpec = Field(UniformValue(minimum=.5, maximum=2))
    initial_value: ValueSpec = Field(default_factory=ConstantValue)
    depreciation_rate: FiniteFloat = Field(default=0.02, ge=0, le=1)
    seed: int = Field(default=42, ge=0, le=2**53 - 1)


class ModelSettings(AppModel):
    team_size: int = Field(default=4, gt=0)
    efficiency_min: FiniteFloat = Field(default=0.5, gt=0)
    efficiency_max: FiniteFloat = Field(default=1.5, gt=0)
    distribution: Literal["linear", "normal"] = "linear"
    deployment_cadence: int = Field(default=5, ge=0)
    qa_size: int = Field(default=5, gt=0)
    qa_time_cost: FiniteFloat = Field(default=0.1, ge=0)
    qa_failure_rate: FiniteFloat = Field(default=0.15, ge=0, le=1)
    qa_failure_cost: FiniteFloat = Field(default=0.25, ge=0, le=1)
    toolchain_size: int = Field(default=20, gt=0)
    deployment_duration: FiniteFloat = Field(default=0.25, ge=0)
    deployment_failure_rate: FiniteFloat = Field(default=0.1, ge=0, le=1)
    support_interval: FiniteFloat | None = Field(default=5, gt=0)
    support_task_story_points: FiniteFloat = Field(default=2, ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.efficiency_min > self.efficiency_max:
            raise ValueError("minimum efficiency must not exceed maximum")
        return self


SweepValue = FiniteFloat | str | None


class SweepRange(AppModel):
    start: FiniteFloat
    end: FiniteFloat
    step: FiniteFloat = Field(gt=0)


class ScenarioDefinition(AppModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(default="Delivery model", min_length=1, max_length=120)
    revision: int = Field(default=1, gt=0)
    settings: ModelSettings = Field(default_factory=ModelSettings)
    sweeps: dict[str, list[SweepValue] | SweepRange] = Field(default_factory=dict)
    team_seed: int = Field(default=123, ge=0, le=2**53 - 1)
    execution_seed: int = Field(default=456, ge=0, le=2**53 - 1)


class ConcreteScenario(AppModel):
    id: UUID
    definition_id: UUID
    revision: int
    name: str
    settings: ModelSettings
    team_seed: int
    execution_seed: int
    model: ModelInput


class TaskSet(AppModel):
    id: UUID = Field(default_factory=uuid4)
    revision: int = 1
    spec: TaskSetSpec
    content_hash: str
    generator_version: str = GENERATOR_VERSION
    tasks: list[TaskInput]


class EditorRequest(AppModel):
    expected_revision: int = Field(ge=0)
    task_spec: TaskSetSpec
    definitions: list[ScenarioDefinition] = Field(min_length=1, max_length=100)


class Preview(AppModel):
    digest: str
    task_set_id: UUID
    workspace_revision: int
    scenarios: list[ConcreteScenario]
    count: int


class RunRequest(AppModel):
    request_id: UUID
    preview_digest: str
    name: str = Field(default="Baseline", min_length=1, max_length=120)
    intent: Literal["manual", "interactive"] = "manual"
    source_run_id: UUID | None = None
    property: str | None = None
    value: SweepValue = None
    definition_id: UUID | None = None
    family_value: SweepValue = None


RunState = Literal[
    "submitting",
    "queued",
    "running",
    "reconnecting",
    "cancelling",
    "completed",
    "completed_with_errors",
    "cancelled",
    "failed",
]
TERMINAL = {"completed", "completed_with_errors", "cancelled", "failed"}


class OutcomeSummary(AppModel):
    scenario: ConcreteScenario
    status: Status = Status.QUEUED
    cursor: int = 0
    cached: bool = False
    loss_percent: float | None = None
    completion_time: float | None = None
    delivered_value: float | None = None
    error: ErrorEnvelope | None = None


class RunStatus(AppModel):
    id: UUID
    name: str
    task_set_id: UUID
    state: RunState
    intent: str
    job_id: UUID | None = None
    outcomes: list[OutcomeSummary]
    last_cursor: int = 0
    error: ErrorEnvelope | None = None
    pinned: bool = False
    superseded: bool = False
    cancel_requested: bool = False
    retry_paused: bool = False


class Workspace(AppModel):
    id: UUID = Field(default_factory=uuid4)
    revision: int = 0
    task_spec: TaskSetSpec = Field(default_factory=TaskSetSpec)
    definitions: list[ScenarioDefinition] = Field(
        default_factory=lambda: [ScenarioDefinition(sweeps={"team_size": [1, 13, 25], "deployment_cadence": [0, 5, 10]})]
    )
    task_sets: list[TaskSet] = Field(default_factory=list)
    current_task_set: UUID | None = None
    baseline_id: UUID | None = None
    latest_id: UUID | None = None
    runs: list[RunStatus] = Field(default_factory=list)


class ComparisonMutation(AppModel):
    action: Literal["pin", "unpin", "baseline", "delete"]


class StageLoss(AppModel):
    stage: str
    label: str
    loss_percent: float
    visits: int


class ResourceActivity(AppModel):
    stage: str
    label: str
    durations: dict[str, float]
    shares: dict[str, float | None]


class Backlog(AppModel):
    stage: str
    label: str
    time: list[float]
    waiting: list[int]
    reduced: bool = False


class PlotData(AppModel):
    loss_percent: float | None
    stages: list[StageLoss]
    activity: list[ResourceActivity]
    backlog: list[Backlog]


class Observation(AppModel):
    rule: str
    message: str
    evidence: str
    property: str | None = None
    value: SweepValue = None


class ResultView(AppModel):
    scenario_id: UUID
    metrics: PlotData
    observations: list[Observation]


class AppConfig(AppModel):
    limits: dict[str, int | float]
    ready: bool
    error: ErrorEnvelope | None = None
    generator_version: str = GENERATOR_VERSION
    engine_version: str = ENGINE_VERSION

"""Version 1 JSON contract for simulation jobs."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskInput(WireModel):
    initial_value: FiniteFloat = Field(ge=0)
    story_points: FiniteFloat = Field(ge=0)
    depreciation_rate: FiniteFloat = Field(default=0.005, ge=0, le=1)
    task_name: str | None = None
    creation_sim_t: FiniteFloat = Field(default=0, ge=0)
    task_type: Literal["development", "support"] = "development"


class DeveloperInput(WireModel):
    name: str = ""
    efficiency: FiniteFloat = Field(default=1, gt=0)


class QAInput(WireModel):
    time_cost: FiniteFloat = Field(default=0.1, ge=0)
    failure_rate: FiniteFloat = Field(default=0, ge=0, le=1)
    failure_cost: FiniteFloat = Field(default=0, ge=0, le=1)


class ToolchainInput(WireModel):
    deployment_duration: FiniteFloat = Field(ge=0)
    failure_rate: FiniteFloat = Field(default=0, ge=0, le=1)


class QAPoolInput(QAInput):
    kind: Literal["pool"] = "pool"
    limit: int = Field(gt=0)


class QAListInput(WireModel):
    kind: Literal["list"] = "list"
    resources: list[QAInput] = Field(min_length=1)


class ToolchainPoolInput(ToolchainInput):
    kind: Literal["pool"] = "pool"
    limit: int = Field(gt=0)


class ToolchainListInput(WireModel):
    kind: Literal["list"] = "list"
    resources: list[ToolchainInput] = Field(min_length=1)


class ModelInput(WireModel):
    developer_team: list[DeveloperInput] = Field(min_length=1)
    deployment_cadence: int = Field(ge=0)
    qa_testers: QAPoolInput | QAListInput
    toolchain_pool: ToolchainPoolInput | ToolchainListInput
    support_interval: FiniteFloat | None = Field(default=None, gt=0)
    support_task_story_points: FiniteFloat = Field(default=1, ge=0)


class JobRequest(WireModel):
    tasks: list[TaskInput] = Field(min_length=1)
    models: list[ModelInput] = Field(min_length=1)
    seed: int | None = Field(default=None, ge=0)


class SummaryData(WireModel):
    completion_time: FiniteFloat
    total_delivered_value: FiniteFloat
    loss: FiniteFloat


class TaskEventData(WireModel):
    event: str
    event_type: Literal["start", "end", "terminal"]
    time: FiniteFloat
    status: Literal["success", "failure"]
    loss: FiniteFloat
    task_type: Literal["development", "support"]
    is_rework: bool
    duration: FiniteFloat | None = None
    resource_id: UUID | None = None


class ResourceMetadataData(WireModel):
    time: FiniteFloat
    state: str
    waiting: int
    allocated: int
    active: int
    success_t: FiniteFloat | None = None
    failure_t: FiniteFloat | None = None
    interruption_t: FiniteFloat | None = None
    waiting_t: FiniteFloat | None = None
    idle_t: FiniteFloat | None = None


class MetadataData(WireModel):
    event_metadata: list[TaskEventData]
    resource_metadata: list[ResourceMetadataData]


class ResultData(WireModel):
    model_index: int = Field(ge=0)
    model: ModelInput
    summary_result: SummaryData
    metadata: MetadataData


class ModelError(WireModel):
    model_index: int = Field(ge=0)
    code: str
    message: str


class OutcomeData(WireModel):
    cursor: int = Field(gt=0)
    model_index: int = Field(ge=0)
    status: Literal["succeeded", "failed", "cancelled"]
    result: ResultData | None = None
    error: ModelError | None = None

    @model_validator(mode="after")
    def valid_shape(self):
        if self.status == "succeeded":
            if self.result is None or self.error is not None:
                raise ValueError("succeeded outcome requires only a result")
            if self.result.model_index != self.model_index:
                raise ValueError("result model index does not match outcome")
        elif self.status == "failed":
            if self.error is None or self.result is not None:
                raise ValueError("failed outcome requires only an error")
            if self.error.model_index != self.model_index:
                raise ValueError("error model index does not match outcome")
        elif self.result is not None or self.error is not None:
            raise ValueError("cancelled outcome cannot carry a result or error")
        return self


class OutcomePage(WireModel):
    outcomes: list[OutcomeData]
    next_cursor: int = Field(ge=0)


JobState = Literal["queued", "running", "completed", "completed_with_errors", "cancelled"]


class JobAccepted(WireModel):
    job_id: UUID
    status: JobState
    status_url: str


class JobStatus(WireModel):
    job_id: UUID
    status: JobState
    total_models: int
    queued_models: int
    running_models: int
    succeeded_models: int
    failed_models: int
    cancelled_models: int
    last_cursor: int


class ErrorEnvelope(WireModel):
    code: str
    message: str
    details: dict | None = None


class HealthResponse(WireModel):
    status: Literal["ok"] = "ok"

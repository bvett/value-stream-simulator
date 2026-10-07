"""Version 1 JSON contract for simulation jobs."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class WireModel(BaseModel):
    """Base model for service request and response data."""

    model_config = ConfigDict(extra="forbid")


class TaskInput(WireModel):
    """Defines task data accepted by the simulation service."""

    initial_value: FiniteFloat = Field(ge=0)
    story_points: FiniteFloat = Field(ge=0)
    depreciation_rate: FiniteFloat = Field(default=0.005, ge=0, le=1)
    task_name: str | None = None
    creation_sim_t: FiniteFloat = Field(default=0, ge=0)
    task_type: Literal["development", "support"] = "development"
    is_rework: bool = Field(default=False, init=False)


class DeveloperInput(WireModel):
    """Defines developer configuration accepted by the service."""

    name: str = ""
    efficiency: FiniteFloat = Field(default=1, gt=0)


class QAInput(WireModel):
    """Defines QA tester configuration accepted by the service."""

    time_cost: FiniteFloat = Field(default=0.1, ge=0)
    failure_rate: FiniteFloat = Field(default=0, ge=0, le=1)
    failure_cost: FiniteFloat = Field(default=0, ge=0, le=1)


class ToolchainInput(WireModel):
    """Defines toolchain configuration accepted by the service."""

    deployment_duration: FiniteFloat = Field(ge=0)
    failure_rate: FiniteFloat = Field(default=0, ge=0, le=1)


class QAPoolInput(QAInput):
    """Defines a pool of QA testers."""

    kind: Literal["pool"] = "pool"
    limit: int = Field(gt=0)


class QAListInput(WireModel):
    """Defines a list of QA tester configurations."""

    kind: Literal["list"] = "list"
    resources: list[QAInput] = Field(min_length=1)


class ToolchainPoolInput(ToolchainInput):
    """Defines a pool of toolchains."""

    kind: Literal["pool"] = "pool"
    limit: int = Field(gt=0)


class ToolchainListInput(WireModel):
    """Defines a list of toolchain configurations."""

    kind: Literal["list"] = "list"
    resources: list[ToolchainInput] = Field(min_length=1)


class ModelInput(WireModel):
    """Defines a simulation model accepted by the service."""

    developer_team: list[DeveloperInput] = Field(min_length=1)
    deployment_cadence: int = Field(ge=0)
    qa_testers: QAPoolInput | QAListInput
    toolchain_pool: ToolchainPoolInput | ToolchainListInput
    support_interval: FiniteFloat | None = Field(default=None, gt=0)
    support_task_story_points: FiniteFloat = Field(default=1, ge=0)


class JobRequest(WireModel):
    """Defines a simulation job submission."""

    tasks: list[TaskInput] = Field(min_length=1)
    models: list[ModelInput] = Field(min_length=1)
    seed: int | None = Field(default=None, ge=0)
    model_seeds: list[Annotated[int, Field(ge=0)]] | None = None
    submission_id: UUID | None = None

    @model_validator(mode="after")
    def validate_seeds(self):
        if self.model_seeds is not None:
            if self.seed is not None:
                raise ValueError("seed and model_seeds are mutually exclusive")
            if len(self.model_seeds) != len(self.models):
                raise ValueError("model_seeds must have one seed per model")
        return self


class SummaryData(WireModel):
    """Stores summary metrics returned for a simulation."""

    completion_time: FiniteFloat
    total_delivered_value: FiniteFloat
    loss: FiniteFloat


class TaskEventData(WireModel):
    """Stores one serialized task event."""

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
    """Stores serialized metadata for one resource."""

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
    """Stores serialized simulation metadata."""

    event_metadata: list[TaskEventData]
    resource_metadata: list[ResourceMetadataData]


class ResultData(WireModel):
    """Stores one serialized simulation result."""

    model_index: int = Field(ge=0)
    model: ModelInput
    summary_result: SummaryData
    metadata: MetadataData


class ModelError(WireModel):
    """Stores an error reported for one model."""

    model_index: int = Field(ge=0)
    code: str
    message: str


class Status(StrEnum):
    """Enumerates the possible job states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutcomeData(WireModel):
    """Stores one simulation outcome returned by a job."""

    cursor: int = Field(gt=0)
    model_index: int = Field(ge=0)
    status: Literal[Status.SUCCEEDED, Status.FAILED, Status.CANCELLED]
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
    """Stores a page of simulation outcomes."""

    outcomes: list[OutcomeData]
    next_cursor: int = Field(ge=0)


JobState = Literal["queued", "running", "completed", "completed_with_errors", "cancelled"]


class JobAccepted(WireModel):
    """Confirms that a simulation job was accepted."""

    job_id: UUID
    status: JobState
    status_url: str


class JobStatus(WireModel):
    """Stores the current state of a simulation job."""

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
    """Wraps a service error response."""

    code: str
    message: str
    details: dict | None = None


class HealthResponse(WireModel):
    """Reports the service health state."""

    status: Literal["ok"] = "ok"

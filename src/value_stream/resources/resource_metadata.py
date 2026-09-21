from pydantic import BaseModel, ConfigDict, field_serializer
from typing import Optional
from value_stream.task import TaskState


class ResourceMetadata(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    time: float
    state: TaskState
    waiting: int = 0
    allocated: int = 0
    active: int = 0
    success_t: Optional[float] = None
    failure_t: Optional[float] = None
    interruption_t: Optional[float] = None
    waiting_t: Optional[float] = None
    idle_t: Optional[float] = None

    @field_serializer('state')
    def serialize_event(self, state: TaskState):
        return state.value

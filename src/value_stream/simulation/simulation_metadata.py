from pydantic import BaseModel
from value_stream.task import TaskEvent
from value_stream.resources import ResourceMetadata
from .model import Model


class SimulationMetadata(BaseModel):
    """Stores metadata about one simulation run."""

    model: Model
    resource_metadata: list[ResourceMetadata]
    event_metadata: list[TaskEvent]

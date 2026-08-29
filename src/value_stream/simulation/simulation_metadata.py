from value_stream.task import TaskEvent

from value_stream.resources import ResourceMetadata
from .model import Model


class SimulationMetadata:
    def __init__(self, model: Model,
                 resource_metadata: list[ResourceMetadata],
                 event_metadata: list[TaskEvent]):
        self.model = model
        self.resource_metadata = resource_metadata
        self.event_metadata = event_metadata

from .model import Model
from .resources import ResourceMetadataSnapshot
from .task_event import TaskEvent


class SimulationMetadata:
    def __init__(self, model: Model,
                 resource_metadata: list[ResourceMetadataSnapshot],
                 event_metadata: list[TaskEvent]):
        self.model = model
        self.resource_metadata = resource_metadata
        self.event_metadata = event_metadata

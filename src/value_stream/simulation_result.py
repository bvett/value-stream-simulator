from .model import Model
from .simulation_metadata import SimulationMetadata


class SummaryResult:

    def __init__(self, model: Model,
                 completion_time: float,
                 total_delivered_value: float,
                 loss: float) -> None:

        self.model = model
        self.completion_time = completion_time
        self.total_delivered_value = total_delivered_value
        self.loss = loss


class SimulationResult:

    def __init__(self, summary_result: SummaryResult, metadata: SimulationMetadata):
        self.summary_result = summary_result
        self.metadata: SimulationMetadata = metadata

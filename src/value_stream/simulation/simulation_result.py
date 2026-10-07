from pydantic import BaseModel

from .model import Model
from .simulation_metadata import SimulationMetadata


class SummaryResult(BaseModel):
    """Stores aggregate metrics for a simulation run."""

    model: Model
    completion_time: float
    total_delivered_value: float
    loss: float


class SimulationResult(BaseModel):
    """Stores detailed results for one simulation run."""

    summary_result: SummaryResult
    metadata: SimulationMetadata

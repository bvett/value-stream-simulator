from pydantic import BaseModel

from .model import Model
from .simulation_metadata import SimulationMetadata


class SummaryResult(BaseModel):
    model : Model
    completion_time : float
    total_delivered_value : float
    loss: float

class SimulationResult(BaseModel):
    summary_result : SummaryResult
    metadata : SimulationMetadata


"""Client errors that preserve partial batch outcomes."""

from value_stream.simulation import SimulationResult
from value_stream.service.schemas import ModelError


class ServiceClientError(RuntimeError):
    """Base error raised by the web service client."""


class BatchSimulationError(ServiceClientError):
    """Reports a failure while running a batch of simulations."""

    def __init__(
        self,
        successful_results: list[tuple[int, SimulationResult]],
        errors: dict[int, ModelError],
    ):
        self.successful_results = successful_results
        self.errors = errors
        super().__init__(f"{len(errors)} model(s) failed: {sorted(errors)}")


class JobCancelledError(ServiceClientError):
    """Reports that a simulation job was cancelled."""

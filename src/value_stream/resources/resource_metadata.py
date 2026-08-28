from typing import Optional
from value_stream.core import WorkflowStateName


class ResourceMetadata:

    def __init__(self,
                 time: float,
                 state: WorkflowStateName,
                 allocated: int = 0,
                 active: int = 0,
                 success_t: Optional[float] = None,
                 failure_t: Optional[float] = None,
                 interruption_t: Optional[float] = None,
                 waiting_t: Optional[float] = None,
                 idle_t: Optional[float] = None):

        self.time = time
        self.state = state
        self.allocated = allocated
        self.active = active
        self.success_t = success_t
        self.failure_t = failure_t
        self.interruption_t = interruption_t
        self.waiting_t = waiting_t
        self.idle_t = idle_t

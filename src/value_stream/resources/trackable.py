from uuid import UUID
from typing import Optional
from value_stream.core import WorkflowStateName


class Trackable:
    """Base class for tracking resource utilization"""

    def __init__(self, workflow_state: WorkflowStateName):
        self.workflow_state = workflow_state
        self.tracker_id: Optional[UUID] = None

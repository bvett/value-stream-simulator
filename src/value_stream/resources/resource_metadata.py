from ..workflow_state_name import WorkflowStateName


class ResourceMetadataSnapshot:
    def __init__(self,
                 time: float,
                 workflow_state: WorkflowStateName,
                 busy_resources: int,
                 idle_resources: int):

        self.time = time
        self.workflow_state = workflow_state
        self.busy_resources = busy_resources
        self.idle_resources = idle_resources

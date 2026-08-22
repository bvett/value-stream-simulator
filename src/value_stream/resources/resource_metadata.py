from ..workflow_state_name import WorkflowStateName


class ResourceMetadataSnapshot:
    def __init__(self,
                 time: float,
                 workflow_state: WorkflowStateName,
                 tasks_waiting: int,
                 busy_resources: int,
                 idle_resources: int):
        # queuing_loss: float,
        # processing_loss: float,
        # interruption_loss: float,
        # failure_loss: float):
        self.time = time
        self.workflow_state = workflow_state
        self.tasks_waiting = tasks_waiting
        self.busy_resources = busy_resources
        self.idle_resources = idle_resources
        # self.queuing_loss = queuing_loss
        # self.processing_loss = processing_loss
        # self.interruption_loss = interruption_loss
        # self.failure_loss = failure_loss

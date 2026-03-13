from enum import StrEnum


class WorkflowStateName(StrEnum):
    PENDING = "pending"
    DEVELOPMENT = "development"
    DEV_COMPLETE = "dev_complete"
    DEPLOYMENT = "deployment"
    DELIVERY = "delivery"

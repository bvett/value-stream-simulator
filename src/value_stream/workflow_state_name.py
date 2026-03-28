from enum import StrEnum


class WorkflowStateName(StrEnum):
    PENDING = "pending"
    DEVELOPMENT = "development"
    DEV_COMPLETE = "dev_complete"
    QA_TESTING = "qa_testing"
    QA_COMPLETE = "qa_complete"
    DEPLOYMENT = "deployment"
    DELIVERY = "delivery"

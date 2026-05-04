from enum import StrEnum


class EventStatus(StrEnum):
    """Outcome status of the event."""
    SUCCESS = 'success'
    FAILURE = 'failure'

from enum import Enum


class AssignmentStrategy(Enum):
    """Specifies how support work is assigned to a set of developers"""
    RANDOM = 1
    CYCLIC = 2  # round-robin for a more even distribution of workload

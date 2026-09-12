from enum import Enum


class AssignmentStrategy(Enum):
    RANDOM = 1
    CYCLIC = 2  # round-robin for a more even distribution of workload
    OWNER = 3
    NEXT_AVAILABLE = 4

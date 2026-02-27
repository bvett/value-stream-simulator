import json
import statistics

from typing import Any
from .model import Model
from .task import Task


class SimulationResult:
    def __init__(self, model: Model, tasks: list[Task]):
        self.model = model
        self.tasks = tasks

    def loss(self) -> float:
        return statistics.mean([t.loss() for t in self.tasks])

    def delivered_value(self) -> float:
        return sum([t.delivered_value() for t in self.tasks])

    def to_json(self, indent: int | None = None) -> bytes:

        def custom_dict(o: Any):
            if hasattr(o.__class__, "to_dict") and callable(getattr(o.__class__, "to_dict")):
                return o.to_dict()

            return o.__dict__

        return json.dumps(self, indent=indent, default=custom_dict).encode('utf-8')

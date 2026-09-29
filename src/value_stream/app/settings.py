"""Bounded single-instance application configuration."""

import os
import math
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class AppSettings:
    max_workspaces: int = 4
    max_task_sets: int = 20
    max_definitions: int = 100
    max_tasks: int = 1000
    max_models: int = 500
    max_resources: int = 100
    max_axis_values: int = 32
    max_pins: int = 12
    max_active_runs: int = 4
    max_retained_runs: int = 32
    max_body_bytes: int = 2 * 1024 * 1024
    max_input_bytes: int = 16 * 1024 * 1024
    max_result_bytes: int = 1024 * 1024 * 1024
    max_run_bytes: int = 1024 * 1024 * 1024
    max_model_bytes: int = 8 * 1024 * 1024
    poll_seconds: float = 0.5
    retry_seconds: float = 60.0
    min_interactive_seconds: float = 1.0

    def __post_init__(self):
        if any(
            not math.isfinite(getattr(self, f.name)) or getattr(self, f.name) <= 0
            for f in fields(self)
        ):
            raise ValueError("application limits must be finite and positive")

    @classmethod
    def from_environment(cls):
        defaults = cls()
        values = {}
        for f in fields(cls):
            key = "VALUE_STREAM_APP_" + f.name.upper()
            if key in os.environ:
                values[f.name] = type(getattr(defaults, f.name))(os.environ[key])
        return cls(**values)

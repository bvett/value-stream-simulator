"""Configurable limits for a demonstration service instance."""

import os
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ServiceSettings:
    max_tasks: int = 1000
    max_models: int = 100
    max_body_bytes: int = 2 * 1024 * 1024
    max_active_jobs: int = 4
    max_queued_jobs: int = 4
    max_model_workers: int = min(4, os.cpu_count() or 1)
    max_model_seconds: float = 120.0
    max_model_outcome_bytes: int = 8 * 1024 * 1024
    max_job_outcome_bytes: int = 64 * 1024 * 1024
    max_retained_jobs: int = 64
    max_retained_bytes: int = 256 * 1024 * 1024
    job_ttl_seconds: float = 3600.0

    def __post_init__(self):
        if any(getattr(self, item.name) <= 0 for item in fields(self)):
            raise ValueError("all service limits must be positive")

    @classmethod
    def from_environment(cls) -> "ServiceSettings":
        values = {}
        defaults = cls()
        for item in fields(cls):
            name = f"VALUE_STREAM_{item.name.upper()}"
            if name in os.environ:
                default = getattr(defaults, item.name)
                values[item.name] = type(default)(os.environ[name])
        return cls(**values)

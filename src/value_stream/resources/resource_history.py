from typing import Optional, Self

from .resource_metadata import ResourceMetadata


class ResourceHistory:

    _instance: Optional[Self] = None

    @classmethod
    def get(cls) -> list[ResourceMetadata]:
        if cls._instance is None:
            cls._instance = cls()

        return cls._instance.data

    @classmethod
    def append(cls, metadata: ResourceMetadata) -> None:
        if cls._instance is None:
            cls._instance = cls()

        return cls._instance.data.append(metadata)

    @classmethod
    def start_epoch(cls):
        cls._instance = cls()

    def __init__(self):
        self.data: list[ResourceMetadata] = []

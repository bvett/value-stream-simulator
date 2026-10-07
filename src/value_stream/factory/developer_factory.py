from typing import Any
from value_stream.resources import Developer

from .factory import Factory


class DeveloperFactory(Factory):
    """Utility for creating Developer objects"""

    @classmethod
    def create(cls, count: int, **kwargs: Any) -> list[Developer]:
        """Creates Developer objects based on DeveloperFactory configuration.

        Args:
            count (int): number of developers to create
            **kwargs (Any): Kwargs.
        """

        if count <= 0:
            raise ValueError("count must be > 0")

        developers: list[Developer] = []

        for i in range(count):
            args = cls._generate_args(**kwargs)

            developers.append(Developer(name=cls._developer_name(i), **args))

        return developers

    @classmethod
    def _developer_name(cls, index: int) -> str:
        return f"Developer {index}"

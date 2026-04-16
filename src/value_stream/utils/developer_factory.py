from typing import Generator
from ..resources import Developer


class DeveloperFactory:
    """Utility for creating Developer objects"""

    def create(self, count: int, **kwargs) -> list[Developer]:
        """Creates Developer objects based on DeveloperFactory configuration

        Args:
            count (int): number of developers to create

            **kwargs: key-value pairs passed to the Developer constructor. 
                if a value is an iterable (such as a generator), the next
                value is used when creating the Developer

        """

        if count <= 0:
            raise ValueError("count must be > 0")

        developers: list[Developer] = []

        for i in range(count):
            args = {}

            for k, v in kwargs.items():
                if isinstance(v, Generator):
                    args[k] = next(v)
                else:
                    args[k] = v

            developers.append(Developer(name=self._developer_name(i),
                                        **args))

        return developers

    def _developer_name(self, index: int) -> str:
        return f"Developer {index}"

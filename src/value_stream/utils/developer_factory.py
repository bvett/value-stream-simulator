from typing import Any, Generator
from ..resources import Developer


class DeveloperFactory:
    """Utility for creating Developer objects"""

    def __init__(self, efficiency: float | Generator[float, Any, None]):
        """Creates a DeveloperFactory

        Args:

            efficiency (float | Generator[float, Any, None]): 
                when a float is provided, sets the efficiency of every 
                created Developer object to this value

                when a Generator is provided, call this to obtain the
                 efficiency for each Developer


        """

        self.efficiency = efficiency

    def create(self, count: int) -> list[Developer]:
        """Creates Developer objects based on DeveloperFactory configuration

        Args:
            count (int): number of developers to create

        """

        if count <= 0:
            raise ValueError("count must be > 0")

        developers: list[Developer] = []

        for i in range(count):

            if isinstance(self.efficiency, int | float):
                efficiency = self.efficiency
            else:
                efficiency = next(self.efficiency)

            developers.append(Developer(name=self._developer_name(i),
                                        efficiency=efficiency))

        return developers

    def _developer_name(self, index: int) -> str:
        return f"Developer {index}"

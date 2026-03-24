from typing import Literal
import numpy as np
from ..resources import Developer


class DeveloperFactory:
    """Utility for creating Developer objects"""

    def __init__(self, strategy: Literal['equal', 'sd'], efficiency: float | tuple[float, float]):
        """Creates a DeveloperFactory

        Args:
            strategy (Literal[&#39;equal&#39;, &#39;sd&#39;]): Creates Developer objects
              with efficiencies that are either equal or reflect a standard deviation

            efficiency (float | tuple[float, float]): 
            When strategy is 'equal' : Single value representing the efficiency
                for all Developer objects.

            When strategy is 'sd' : Tuple of (low, high) efficiency values.

        """

        self.efficiency = efficiency

        valid_strategies = ['equal', 'sd']

        if strategy not in valid_strategies:
            raise ValueError(f"strategy must be one of {valid_strategies}")

        if strategy == 'equal':
            self.efficiencies = self._equal_efficiencies

        elif strategy == 'sd':
            self.efficiencies = self._stddev_efficiencies

    def create(self, count: int) -> list[Developer]:
        """Creates Developer objects based on DeveloperFactory configuration

        Args:
            count (int): number of developers to create

        """

        if count <= 0:
            raise ValueError("count must be > 0")

        developers = []

        efficiencies = self.efficiencies(count)
        for i in range(count):
            developers.append(
                Developer(name=self._developer_name(i), efficiency=efficiencies[i]))

        return developers

    def _developer_name(self, index: int) -> str:
        return f"Developer {index}"

    def _equal_efficiencies(self, count: int) -> list[float]:
        if not isinstance(self.efficiency, (int, float)):
            raise ValueError(
                "efficiency must be an int or float when strategy is 'equal'")

        return [self.efficiency] * count

    def _stddev_efficiencies(self, count: int) -> list[float]:
        if not isinstance(self.efficiency, tuple) or len(self.efficiency) != 2:
            raise ValueError(
                "efficiency must be a tuple of (low,high) when strategy is 'sd'"
            )

        return np.random.uniform(low=self.efficiency[0],
                                 high=self.efficiency[1],
                                 size=count).tolist()

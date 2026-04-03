from typing import Collection, Iterable

from . import DeveloperFactory
from ..resources import Developer
from ..model import Model


class ModelFactory:
    """Utility for creating Model objects"""

    def __init__(self, toolchain_concurrency: int,
                 deployment_duration: float,
                 developer_factory: DeveloperFactory):
        """Creates a ModelFactory

        Args:
            toolchain_concurrency (int): Number of simultaneous deployments
            deployment_duration (float): Duration in time units of a deployment
        """

        self.toolchain_concurrency = toolchain_concurrency
        self.deployment_duration = deployment_duration

        self.developer_factory = developer_factory

    def create(self, teams: Iterable[int | Collection[Developer]],
               deployment_cadences: range, num_qa_resources: int) -> list[Model]:
        """Creates Model objects

        Args:
            developer_teams (list[list[Developer]]): Separate collections of Developer objects
            deployment_cadences (range): List or range of deployment cadences

        Returns:
            list[Model]: One model is returned for each combination
            of developer_teams and deployment_cadences.
        """

        result = []

        for t in teams:

            if isinstance(t, int):
                team = self.developer_factory.create(t)
            elif isinstance(t, Collection):
                team = t
            else:
                raise ValueError("invalid value for teams")

            for cadence in deployment_cadences:
                result.append(Model(developer_team=team,
                                    toolchain_concurrency=self.toolchain_concurrency,
                                    deployment_duration=self.deployment_duration,
                                    deployment_cadence=cadence,
                                    num_qa_resources=num_qa_resources))
        return result

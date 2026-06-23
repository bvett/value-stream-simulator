from typing import Collection, Iterable

from ..resources import Developer, QATester, Toolchain
from ..model import Model


class ModelFactory:
    """Utility for creating Model objects"""

    def __init__(self):
        """Creates a ModelFactory

        Args:
            toolchain_concurrency (int): Number of simultaneous deployments
            deployment_duration (float): Duration in time units of a deployment
        """

        # self.toolchain_concurrency = toolchain_concurrency
        # self.deployment_duration = deployment_duration

    def create(self, teams: Iterable[Collection[Developer]],
               deployment_cadences: Iterable,
               qa_testers: Iterable[QATester],
               toolchain_pool: Iterable[Toolchain],
               support_intervals: Iterable) -> list[Model]:
        """Creates Model objects

        Args:
            developer_teams (list[list[Developer]]): Separate collections of Developer objects
            deployment_cadences (Iterable): List or range of deployment cadences

        Returns:
            list[Model]: One model is returned for each combination
            of developer_teams and deployment_cadences.
        """

        result = []

        for team in teams:
            for cadence in deployment_cadences:
                for interval in support_intervals:
                    result.append(Model(developer_team=team,
                                        deployment_cadence=cadence,
                                        qa_testers=qa_testers,
                                        toolchain_pool=toolchain_pool,
                                        support_interval=interval))
        return result

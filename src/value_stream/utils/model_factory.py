from ..resources import Developer
from ..model import Model


class ModelFactory:
    """Utility for creating Model objects"""

    def __init__(self, toolchain_concurrency: int,
                 deployment_duration: float):
        """Creates a ModelFactory

        Args:
            toolchain_concurrency (int): Number of simultaneous deployments
            deployment_duration (float): Duration in time units of a deployment
        """

        self.toolchain_concurrency = toolchain_concurrency
        self.deployment_duration = deployment_duration

    def create(self, developer_teams: list[list[Developer]],
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

        for team in developer_teams:

            for cadence in deployment_cadences:
                result.append(Model(developer_team=team,
                                    toolchain_concurrency=self.toolchain_concurrency,
                                    deployment_duration=self.deployment_duration,
                                    deployment_cadence=cadence,
                                    num_qa_resources=num_qa_resources))
        return result

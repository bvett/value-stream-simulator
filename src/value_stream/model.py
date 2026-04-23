from typing import Collection, Iterable
from .resources import Developer, QATester, Toolchain


class Model:
    """Set of attributes for controlling a simulation"""

    def __init__(self, developer_team: Collection[Developer],
                 deployment_cadence: int,
                 qa_testers: Iterable[QATester],
                 toolchain_pool: Iterable[Toolchain]) -> None:
        """Describes how a simulation executes

        Args:
            developer_team (list[Developer]): Developers that process tasks
            toolchain_concurrency (int): Max number of deployments that can occur simultaneously
            deployment_duration (float): Duration of a deployment in time units
            deployment_cadence (int): Time interval between deployment activities.
        """

        if deployment_cadence < 0:
            raise ValueError("deployment_cadence must be >=0")

        self.deployment_cadence = deployment_cadence
        self.qa_testers = qa_testers

        self.toolchain_pool = toolchain_pool

        self.developer_team = developer_team
        self.team_size = len(developer_team)

from typing import Any, Collection, Tuple
from .resources import Developer


class Model:
    """Set of attributes for controlling a simulation"""

    def __init__(self, developer_team: Collection[Developer],
                 toolchain_concurrency: int,
                 deployment_duration: float,
                 deployment_cadence: int,
                 num_qa_resources: int) -> None:
        """Describes how a simulation executes

        Args:
            developer_team (list[Developer]): Developers that process tasks
            toolchain_concurrency (int): Max number of deployments that can occur simultaneously
            deployment_duration (float): Duration of a deployment in time units
            deployment_cadence (int): Time interval between deployment activities.
        """

        if toolchain_concurrency < 0:
            raise ValueError("toolchain_concurrency must be >=0")

        if deployment_duration < 0:
            raise ValueError("deployment_duration must be >=0")

        if deployment_cadence < 0:
            raise ValueError("deployment_cadence must be >=0")

        if num_qa_resources <= 0:
            raise ValueError("num_qa_resources must by >0")

        self.toolchain_concurrency = toolchain_concurrency
        self.deployment_duration = deployment_duration
        self.deployment_cadence = deployment_cadence
        self.num_qa_resources = num_qa_resources

        self.developer_team = developer_team
        self.team_size = len(developer_team)

from typing import Any
from .developer import Developer


class Model:
    """Set of attributes for controlling a simulation"""

    def __init__(self, developer_team: list[Developer],
                 toolchain_concurrency: int,
                 deployment_duration: float,
                 deployment_cadence: int) -> None:
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

        self.toolchain_concurrency = toolchain_concurrency
        self.deployment_duration = deployment_duration
        self.deployment_cadence = deployment_cadence

        self.developer_team = developer_team

    @property
    def team_size(self) -> int:
        """Returns the number of developers in this model"""
        return len(self.developer_team)

    def __str__(self) -> str:
        return "Model:\n"\
            f"\tDeployment Cadence: {self.deployment_cadence}\n"\
            f"\tToolchain Concurrency: {self.toolchain_concurrency}\n"\
            f"\tDeployment Duration: {self.deployment_duration}\n"\
            f"\tTeam Size: {self.team_size}"

    def to_dict(self) -> dict[str, Any]:
        """Injects calculated properties during json serialization"""

        custom_additions = {
            "team_size": self.team_size}

        return vars(self) | custom_additions

from typing import Iterable, Optional
from pydantic import BaseModel, computed_field,  NonNegativeInt, Field, FiniteFloat
from value_stream.resources import Developer, QATester, Toolchain, ResourcePool

class Model(BaseModel):
    developer_team: list[Developer]
    deployment_cadence: NonNegativeInt
    qa_testers: ResourcePool | Iterable[QATester]
    toolchain_pool: ResourcePool | Iterable[Toolchain]
    support_interval: Optional[float] = Field(default=None, gt=0)
    support_task_story_points: FiniteFloat = Field(default=1, ge=0)

    """Describes how a simulation executes

    Args:
        developer_team (list[Developer]): Developers that process tasks
        toolchain_concurrency (int): Max number of deployments that can occur simultaneously
        deployment_duration (float): Duration of a deployment in time units
        deployment_cadence (int): Time interval between deployment activities.
        support_interval (float|None): Frequency of support task generation.  
        support_task_story_points (float): Number of story points assigned to generated support tasks.
    """

    @computed_field
    @property
    def team_size(self) -> int:
        return len(self.developer_team)


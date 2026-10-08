import copy
import itertools
from typing import Iterable, Optional

from value_stream.resources import Developer, QATester, Toolchain
from .model import Model


class ModelFactory:
    """Utility for creating Model objects"""

    @classmethod
    def create(
        cls,
        teams: Iterable[list[Developer]],
        deployment_cadences: Iterable,
        qa_testers: Iterable[QATester],
        toolchain_pool: Iterable[Toolchain],
        support_intervals: Optional[Iterable] = None,
        support_task_story_points: float = 1,
    ) -> list[Model]:
        """Create one model for each team and deployment cadence combination.

        Args:
            teams (Iterable[list[Developer]]): Developer teams to combine with the other model settings.
            deployment_cadences (Iterable): Deployment cadences to test.
            qa_testers (Iterable[QATester]): QA testers available to each model.
            toolchain_pool (Iterable[Toolchain]): Toolchains available to each model.
            support_intervals (Optional[Iterable]): Support intervals to test.
            support_task_story_points (float): Work assigned to each support task.

        Returns:
            list[Model]: Models generated from each team and deployment cadence combination.
        """

        if support_intervals is None:
            support_intervals = [None]

        result = []

        for team, cadence, interval in itertools.product(
            teams, deployment_cadences, support_intervals
        ):
            result.append(
                Model(
                    developer_team=copy.deepcopy(team),
                    deployment_cadence=cadence,
                    qa_testers=qa_testers,
                    toolchain_pool=toolchain_pool,
                    support_interval=interval,
                    support_task_story_points=support_task_story_points,
                )
            )
        return result

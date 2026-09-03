import copy
import itertools
from typing import Collection, Iterable, Optional

from value_stream.simulation import Model
from value_stream.resources import Developer, QATester, Toolchain


class ModelFactory:
    """Utility for creating Model objects"""

    @classmethod
    def create(self, teams: Iterable[Collection[Developer]],
               deployment_cadences: Iterable,
               qa_testers: Iterable[QATester],
               toolchain_pool: Iterable[Toolchain],
               support_intervals: Optional[Iterable] = None,
               support_task_story_points: float = 1) -> list[Model]:
        """Creates Model objects

        Args:
            developer_teams (list[list[Developer]]): Separate collections of Developer objects
            deployment_cadences (Iterable): List or range of deployment cadences

        Returns:
            list[Model]: One model is returned for each combination
            of developer_teams and deployment_cadences.
        """

        if support_intervals is None:
            support_intervals = [None]

        result = []

        for team, cadence, interval in itertools.product(teams, deployment_cadences, support_intervals):
            result.append(Model(developer_team=copy.deepcopy(team),
                                deployment_cadence=cadence,
                                qa_testers=qa_testers,
                                toolchain_pool=toolchain_pool,
                                support_interval=interval,
                                support_task_story_points=support_task_story_points))
        return result

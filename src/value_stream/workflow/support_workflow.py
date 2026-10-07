from typing import Optional
from value_stream.factory import TaskFactory, TaskGenerator
from value_stream.task import SupportTask


class SupportWorkflow(TaskGenerator):
    """Generates and processes recurring support tasks."""

    def __init__(self, story_points: float, group_size: int = 1, limit: Optional[int] = None) -> None:
        """Configure generation of recurring support tasks.

        Args:
            story_points (float): Amount of work to apply.
            group_size (int): Number of tasks generated in each group.
            limit (Optional[int]): Maximum number of items allowed.
        """
        super().__init__(
            factory=TaskFactory(SupportTask, story_points=story_points),
            group_size=group_size,
            limit=limit,
        )

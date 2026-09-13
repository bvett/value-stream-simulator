from typing import Optional
from value_stream.factory import TaskFactory, TaskGenerator
from value_stream.task import SupportTask


class SupportWorkflow(TaskGenerator):
    def __init__(self, story_points: float, group_size: int = 1, limit: Optional[int] = None):
        super().__init__(factory=TaskFactory(SupportTask,
                                             story_points=story_points), group_size=group_size, limit=limit)

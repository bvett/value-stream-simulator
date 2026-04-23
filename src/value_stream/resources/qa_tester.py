from .resource import Resource
from ..task import Task
from ..workflow_state_name import WorkflowStateName


class QATester(Resource):
    def __init__(self, time_cost: float = 0.1):
        super().__init__(workflow_state=WorkflowStateName.QA_TESTING)
        self.time_cost = time_cost

    def effort(self, tasks: list[Task]) -> float:
        return sum(task.complexity * self.time_cost for task in tasks)


class QATesterPool:
    def __init__(self, limit: int | None = None, **kwargs):

        if limit is not None and limit <= 0:
            raise ValueError("limit must be None or >0")

        self.limit = limit
        self.kwargs = kwargs
        self._i = 0

    def __next__(self):

        if self.limit is None:
            return QATester(**self.kwargs)

        if self._i < self.limit:
            self._i += 1
            return QATester(**self.kwargs)

        raise StopIteration

    def __iter__(self):
        self._i = 0
        return self

from value_stream.task import Task


class ResourcePolicy:
    def task_priority(self, tasks_1: list[Task], tasks_2: list[Task]):
        raise NotImplementedError

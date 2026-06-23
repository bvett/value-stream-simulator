from ..task import Task
from .task_factory import TaskFactory


from simpy import Environment, Interrupt, Process, Store


class TaskGenerator:
    """creates a set of Tasks at a regular simulation time interval. 
    Useful for simulating task creation over time and the creation of unexpected toil.
    """

    def __init__(self,  factory: TaskFactory,  interval: float, group_size: int = 1, limit: int | None = None):

        if interval <= 0:
            raise ValueError("interval must be > 0")

        self.group_size = group_size
        self.factory = factory
        self.interval = interval

        self.proc: Process | None = None
        self._batch_num = 0
        self.limit = limit

    def __iter__(self):
        return self

    def __next__(self):
        self._batch_num += 1
        serial_num = 0

        tasks = self.factory.create(count=self.group_size)

        for task in tasks:
            if self.group_size == 1:
                task.task_id = f"S{self._batch_num}"
            else:
                serial_num += 1
                task.task_id = f"S{self._batch_num}-{serial_num}"

        return tasks

    def start(self, env: Environment, target: Store, baseline_time: float = 0):
        self._batch_num = 0

        def gen(limit: int | None):

            while True:

                if limit is not None:
                    if limit == 0:
                        break

                    limit -= 1

                try:
                    value: list[Task] = next(self)

                    event = env.timeout(delay=self.interval, value=value)
                    yield event

                    if event.value is None:
                        raise RuntimeError("Unexpected empty value")

                    for v in event.value:
                        v.creation_t = env.now - baseline_time
                        v.history.baseline_t = baseline_time
                        yield target.put(v)

                except Interrupt:
                    break
        self.proc = env.process(gen(self.limit))

    def stop(self):
        if self.proc is not None:
            self.proc.interrupt()

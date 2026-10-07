from typing import Any, Generator
import random
from pydantic import FiniteFloat, Field
from simpy import Environment, Timeout

from value_stream.task import EventStatus, Task

from .resource import Resource
from .resource_pool import PooledResource


class QATester(Resource, PooledResource):
    """Tests completed development tasks and reports pass or failure."""

    time_cost: FiniteFloat = Field(default=0.1)
    failure_rate: FiniteFloat = Field(default=0.0, ge=0, le=1)
    failure_cost: FiniteFloat = Field(default=0.0, ge=0, le=1)

    def do_work(
        self, env: Environment, tasks: list[Task]
    ) -> Generator[Timeout, Any, dict[str, EventStatus]]:
        """Test tasks and yield until the QA work completes.

        Args:
            env (Environment): Simulation environment.
            tasks (list[Task]): Tasks to process.

        Yields:
            Timeout: Event that completes QA work.

        Returns:
            dict[str, EventStatus]: Work result and completion status.
        """
        effort = sum(task.story_points * self.time_cost for task in tasks)

        if random.random() < self.failure_rate:
            result = EventStatus.FAILURE
        else:
            result = EventStatus.SUCCESS

        work = env.timeout(effort, value={"result": result})

        yield work

        # Cost of remediation is a perceentage of original effort
        if result == EventStatus.FAILURE:
            for task in tasks:
                remediation_work = task.story_points * self.failure_cost
                task.do_work(-remediation_work)

        return work.value

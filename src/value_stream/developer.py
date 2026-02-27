import copy
import logging

from simpy import Environment, Store
from .task import Task

logger = logging.getLogger(__name__)


class Developer:
    """Simulates software development activity on a Task"""

    def __init__(self, efficiency: float = 1.0, name: str | None = None) -> None:
        """Creates a Developer

        Args:
            efficiency (float): Relative performance of the developer.
            name (str): Optional identifier.


        """
        self.name: str = name if name else ""

        if efficiency <= 0:
            raise ValueError("efficiency must be > 0")

        self.efficiency: float = efficiency

    def develop(self, env: Environment, task: Task, target: Store):
        """Simulates development 

        Time spent on development is calculated by dividing the complexity 
        of the task by the efficiency of the developer

        Args:
            env (Environment): SimPy Environment
            task_result (TaskResult): Task being developed
            target (Store): Queue to receive the completed task
        """
        task = copy.deepcopy(task)
        task.history.dev_start_t = env.now

        logging.debug(
            "%s starting development on %s at t=%i", self.name, task.task_id, env.now)

        yield env.timeout(task.complexity / self.efficiency)

        logging.debug(
            "%s completed development on %s at t=%i", self.name, task.task_id, env.now)

        task.history.dev_end_t = env.now

        yield target.put(task)


class DeveloperTeam(Store):
    """Maintains a pool of developers for task allocation"""

    def __init__(self, env: Environment, developers: list[Developer]):
        super().__init__(env, len(developers))
        for developer in developers:
            self.put(developer)

    def start(self, source: Store, target: Store):
        """Main loop for processing task development

        Args:
            source (Store): Origin of tasks to be developed
            target (Store): Destination of tasks after development completes
        """

        while True:
            task = yield source.get()
            logger.debug(
                "Task %s pending assignment to developer at t=%i", task.task_id, self._env.now)

            # Create coroutine to handle development
            self._env.process(
                self._develop(task, target))

    def _develop(self, task: Task, target: Store):

        # Request developer from pool
        developer = yield self.get()
        logger.debug("Task %s assigned to developer %s at t=%i",
                     task.task_id, developer.name, self._env.now)

        # Wait for development to complete and return developer to pool
        yield self._env.process(developer.develop(self._env, task, target))
        yield self.put(developer)

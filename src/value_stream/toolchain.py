import copy
import logging

from simpy import Environment, Resource, Store

from .task import Task

logger = logging.getLogger(__name__)


class Toolchain(Resource):
    """Simulates the post-development portion of a the value stream by processing the delivery of tasks"""

    def __init__(self, env: Environment,
                 deployment_duration: float,
                 deployment_cadence: int,
                 concurrency: int = 1) -> None:
        """Creates a Toolchain

        Args:
            env (Environment): SimPy environment

            deployment_duration (float): fixed number of time units to
              perform a deployment

            deployment_cadence (int): Defines a fixed deployment
              schedule, specified as the number of time units between
              deployments.  0 represents on-demand, continuous
              deployment

            concurrency (int, optional): Number of deployments that can be 
              happening at the same time. Defaults to 1.

        """
        super().__init__(env, concurrency)

        if deployment_duration < 0:
            raise ValueError("deployment_duration must be >= 0")

        self.deployment_duration = deployment_duration

        if deployment_cadence < 0:
            raise ValueError("deployment_cadence must be >= 0")

        self.deployment_cadence = deployment_cadence

    def start(self, source: Store, target: Store):

        if self.deployment_cadence == 0:
            while True:
                task = yield source.get()
                task = copy.deepcopy(task)
                self._env.process(self._do_deployment([task], target))

        else:

            while True:

                yield self._env.timeout(self.deployment_cadence)
                yield self._env.timeout(0)

                queue = []

                while len(source.items) > 0:
                    task = yield source.get()
                    task = copy.deepcopy(task)
                    queue.append(task)

                self._env.process(self._do_deployment(
                    queue.copy(), target))

    def _do_deployment(self, tasks: list[Task], target: Store):

        if not tasks:
            return

        with self.request() as req:

            logger.debug("Waiting for toolchain resource")
            yield req

            for task in tasks:
                task.history.delivery_start_t = self._env.now
            logger.debug("Deployment of %i tasks starting at %i",
                         len(tasks), self._env.now)
            yield self._env.timeout(self.deployment_duration)
            logger.debug("Deployment of %i tasks completed at %i",
                         len(tasks), self._env.now)
            for task in tasks:
                task.history.delivery_end_t = self._env.now
                yield target.put(task)

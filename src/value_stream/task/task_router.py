from abc import ABC, abstractmethod

from typing import Optional
from simpy import Store
from simpy.resources.store import StorePut

from value_stream.core import EventStatus, TaskType
from .task import Task


class TaskRouter:
    def __init__(self, route_1: 'Store | TaskRouter', route_2: Optional['Store | TaskRouter']):
        self._route_1 = route_1
        self._route_2 = route_2

    @abstractmethod
    def route(self, task: Task, status: Optional[EventStatus] = None) -> StorePut:
        pass

    @classmethod
    def _send_to(cls, task: Task, route: Optional['Store | TaskRouter'], status: Optional[EventStatus] = None) -> StorePut:
        if route is None:
            raise RuntimeError("route is None")

        if isinstance(route, Store):
            return route.put(task)

        if isinstance(route, TaskRouter):
            return route.route(task=task, status=status)

        raise RuntimeError("Unknown route type")


class DefaultRouter(TaskRouter):
    def __init__(self, route: 'Store | TaskRouter'):
        super().__init__(route_1=route, route_2=None)

    def route(self, task: Task, status: Optional[EventStatus] = None) -> StorePut:
        return self._send_to(task, self._route_1, status)


class StatusRouter(TaskRouter):
    def __init__(self, on_success: 'Store | TaskRouter', on_failure: 'Store | TaskRouter'):
        super().__init__(route_1=on_success, route_2=on_failure)

    def route(self, task: Task, status: Optional[EventStatus] = EventStatus.FAILURE) -> StorePut:

        if status == EventStatus.SUCCESS:
            return self._send_to(task, self._route_1, status)

        return self._send_to(task, self._route_2, status)


class TypeRouter(TaskRouter):
    def __init__(self, on_support: 'Store | TaskRouter', on_development: 'Store | TaskRouter'):
        super().__init__(route_1=on_support, route_2=on_development)

    def route(self, task: Task, status: Optional[EventStatus] = None) -> StorePut:

        if task.task_type == TaskType.SUPPORT:
            return self._send_to(task, self._route_1, status)

        return self._send_to(task, self._route_2, status)

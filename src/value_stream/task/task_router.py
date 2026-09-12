from abc import ABC, abstractmethod

from typing import Optional
from simpy import Store
from simpy.resources.store import StorePut

from .event_status import EventStatus
from .task import Task
from .task_type import TaskType


class TaskRouter(ABC):

    @abstractmethod
    def route(self, task: Task, status: Optional[EventStatus] = None) -> StorePut:
        pass

    @classmethod
    def _send_to(cls, task: Task, route: 'Store | TaskRouter', status: Optional[EventStatus] = None) -> StorePut:

        if isinstance(route, Store):
            return route.put(task)

        if isinstance(route, TaskRouter):
            return route.route(task=task, status=status)


class DefaultRouter(TaskRouter):
    def __init__(self, route: 'Store | TaskRouter'):
        self._route = route

    def route(self, task: Task, status: Optional[EventStatus] = None) -> StorePut:
        return self._send_to(task, self._route, status)


class StatusRouter(TaskRouter):
    def __init__(self, on_success: 'Store | TaskRouter', on_failure: 'Store | TaskRouter'):
        self._on_success = on_success
        self._on_failure = on_failure

    def route(self, task: Task, status: Optional[EventStatus] = EventStatus.FAILURE) -> StorePut:

        if status == EventStatus.SUCCESS:
            return self._send_to(task, self._on_success, status)

        return self._send_to(task, self._on_failure, status)


class TypeRouter(TaskRouter):
    def __init__(self, on_support: 'Store | TaskRouter', on_development: 'Store | TaskRouter'):
        self._on_support = on_support
        self._on_failure = on_development

    def route(self, task: Task, status: Optional[EventStatus] = None) -> StorePut:

        if task.task_type == TaskType.SUPPORT:
            return self._send_to(task, self._on_support, status)

        return self._send_to(task, self._on_failure, status)

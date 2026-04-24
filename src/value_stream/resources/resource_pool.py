from typing import Type


class ResourcePool:
    """Generates a fixed or unlimited quantity of a homogeneous resource
    """

    def __init__(self, class_name: Type, limit: int | None = None, **kwargs):

        if limit is not None and limit <= 0:
            raise ValueError("limit must be None or >0")

        self._class = class_name
        self.limit = limit
        self.kwargs = kwargs
        self._i = 0

    def __next__(self):

        if self.limit is None:
            return self._class(**self.kwargs)

        if self._i < self.limit:
            self._i += 1
            return self._class(**self.kwargs)

        raise StopIteration

    def __iter__(self):
        self._i = 0
        return self


class PooledResource:
    @classmethod
    def create_pool(cls, limit: int | None = None, **kwargs):
        return ResourcePool(class_name=cls, limit=limit, **kwargs)

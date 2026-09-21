from typing import Type, Optional, Self
import uuid
from pydantic import BaseModel, Field, PrivateAttr, ConfigDict


class ResourcePool(BaseModel):
    """Generates a fixed or unlimited quantity of a homogeneous resource
    """
    model_config = ConfigDict(extra='allow')
    class_name : Type = Field()
    limit : Optional[int] = Field(default=None, gt=0)
    _i : int = PrivateAttr(default=0, init=False)

    _pool_id : uuid.UUID = PrivateAttr(default_factory=uuid.uuid4)

    def __next__(self):

        if self.limit is None:
            kwargs = {} if not self.model_extra else self.model_extra
            return self.class_name(**kwargs)

        if self._i < self.limit:
            self._i += 1
            kwargs = {} if not self.model_extra else self.model_extra
            return self.class_name(**kwargs)

        raise StopIteration

    def __iter__(self) -> Self: # pyright: ignore[reportIncompatibleMethodOverride]
        self._i = 0
        return self


class PooledResource:
    @classmethod
    def create_pool(cls, limit: Optional[int] = None, **kwargs):
        return ResourcePool(class_name=cls, limit=limit, **kwargs)

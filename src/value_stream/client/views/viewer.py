from enum import Enum
from typing import Any, Optional

from matplotlib import colormaps


class Viewer:
    def __init__(self, colormap: str = 'plasma'):
        self.colormap = colormaps[colormap]

    @classmethod
    def _to_dict(cls, obj: Any, exclusions: Optional[list[str]] = None):

        if exclusions is None:
            exclusions = []

        if isinstance(obj, list):
            return [cls._to_dict(o) for o in obj]

        if isinstance(obj, Enum):
            return obj.value

        if hasattr(obj, '__dict__'):
            result: dict[str, Any] = {}

            for _, (k, v) in enumerate(obj.__dict__.items()):
                if k not in exclusions:
                    result[k] = cls._to_dict(v, exclusions)

            return result
        return obj

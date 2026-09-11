from typing import Any, Generator
import numpy as np


class Factory:

    _rng = np.random.default_rng()

    @classmethod
    def uniform(cls, low: float, high: float) -> Generator[float, Any, None]:
        """produces a uniform distribution as a generator"""
        while True:
            yield cls._rng.uniform(low, high)

    @classmethod
    def _generate_args(cls, **kwargs):
        """returns **kwargs, with any Generator being replaced by its next value
        """
        args = {}

        for k, v in kwargs.items():
            if isinstance(v, Generator):
                args[k] = next(v)
            else:
                args[k] = v

        return args

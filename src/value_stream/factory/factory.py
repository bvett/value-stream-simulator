from typing import Any, Generator
import numpy as np


class Factory:
    """Provides shared helpers for creating configured simulation objects."""

    _rng = np.random.default_rng()

    @classmethod
    def uniform(cls, low: float, high: float) -> Generator[float, Any, None]:
        """Yield samples from a uniform distribution.

        Args:
            low (float): Lower bound of the range.
            high (float): Upper bound of the range.

        Yields:
            float: Successive random samples.
        """

        while True:
            yield cls._rng.uniform(low, high)

    @classmethod
    def _generate_args(cls, **kwargs: Any) -> dict[str, Any]:
        """Resolve generator-valued arguments to their next values.

        Args:
            **kwargs (Any): Values to pass to a factory-created object.

        Returns:
            dict[str, Any]: Arguments with generator values sampled once.
        """
        args = {}

        for k, v in kwargs.items():
            if isinstance(v, Generator):
                args[k] = next(v)
            else:
                args[k] = v

        return args

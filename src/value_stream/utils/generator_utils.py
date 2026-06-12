from typing import Any, Generator

import numpy as np

_rng = np.random.default_rng()


def uniform(low: float, high: float) -> Generator[float, Any, None]:
    """produces a uniform distribution as a generator"""
    while True:
        yield _rng.uniform(low, high)


def generate_args(**kwargs):
    """returns **kwargs, with any Generator being replaced by its next value
    """
    args = {}

    for k, v in kwargs.items():
        if isinstance(v, Generator):
            args[k] = next(v)
        else:
            args[k] = v

    return args

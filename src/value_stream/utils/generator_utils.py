from typing import Any, Generator

import numpy as np

_rng = np.random.default_rng()


def uniform(low: float, high: float) -> Generator[float, Any, None]:
    """produces a uniform distribution as a generator"""
    while True:
        yield _rng.uniform(low, high)

from typing import Any, Generator

import numpy as np


def uniform(low: float, high: float) -> Generator[float, Any, None]:
    """produces a uniform distribution as a generator"""
    while True:
        yield np.random.default_rng().uniform(low, high)

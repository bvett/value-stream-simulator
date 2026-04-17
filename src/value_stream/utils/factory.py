from itertools import product
from typing import Any, Dict, Iterable, Generator


class Factory:

    @classmethod
    def create_matrix(cls, class_name: type[Any], argmap: Dict[str, Iterable]):

        values = argmap.values()
        result = product(*values)

        for r in result:
            kwargs = dict(zip(argmap.keys(), r))
            yield class_name(**kwargs)


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

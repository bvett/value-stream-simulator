from itertools import product
from typing import Any, Dict, Iterable


class Factory:

    @classmethod
    def create_matrix(cls, class_name: type[Any], argmap: Dict[str, Iterable]):

        values = argmap.values()
        result = product(*values)

        for r in result:
            kwargs = dict(zip(argmap.keys(), r))
            yield class_name(**kwargs)

from value_stream.utils import generate_args
from value_stream.resources import Developer


class DeveloperFactory:
    """Utility for creating Developer objects"""

    @classmethod
    def create(cls, count: int, **kwargs) -> list[Developer]:
        """Creates Developer objects based on DeveloperFactory configuration

        Args:
            count (int): number of developers to create

            **kwargs: key-value pairs passed to the Developer constructor. 
                if a value is an iterable (such as a generator), the next
                value is used when creating the Developer

        """

        if count <= 0:
            raise ValueError("count must be > 0")

        developers: list[Developer] = []

        for i in range(count):
            args = generate_args(**kwargs)

            developers.append(Developer(name=cls._developer_name(i),
                                        **args))

        return developers

    @classmethod
    def _developer_name(cls, index: int) -> str:
        return f"Developer {index}"

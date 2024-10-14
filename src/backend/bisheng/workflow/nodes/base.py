from typing import Any


class BaseNode:
    def __init__(self, id: str, name: str, **kwargs: Any) -> None:
        self.id = id
        self.name = name
        self.kwargs = kwargs

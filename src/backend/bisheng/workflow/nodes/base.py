from typing import Any


class BaseNode:
    def __init__(self, id: str, type: str, name: str, description: str, data: Any, **kwargs: Any) -> None:
        self.id = id
        self.type = type
        self.name = name
        self.description = description
        self.data = data


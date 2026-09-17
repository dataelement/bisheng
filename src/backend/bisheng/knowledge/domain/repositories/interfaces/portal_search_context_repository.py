"""门户请求关联资料的只读批量接口。"""

from typing import Any, Protocol


class PortalSearchContextRepository(Protocol):
    async def load(self, kind: str, ids: list[int]) -> dict[int, Any]: ...

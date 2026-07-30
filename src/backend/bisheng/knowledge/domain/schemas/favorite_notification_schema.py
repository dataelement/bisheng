from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class FavoriteRecipientSnapshot(BaseModel):
    """删除后无法重新鉴权时使用的最小接收人快照。"""

    user_id: int
    favorite_space_id: int


class FavoriteChangeEvent(BaseModel):
    """收藏源文件的一项字段级变化。"""

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    tenant_id: int
    source_space_id: int
    source_file_id: int
    file_name: str
    action_code: str
    before_value: Any = None
    after_value: Any = None
    actor_user_id: int
    actor_user_name: str | None = None
    recipient_snapshots: list[FavoriteRecipientSnapshot] | None = None


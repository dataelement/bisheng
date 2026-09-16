"""附件元信息 —— 应用被允许知道的全部（design D9）。

刻意**没有** bucket、对象键、端点地址、存储凭据、签名：应用只见附件的应用内
路径与元信息。两个后端（平台存储 / 本地目录）产出同一个形状，于是"本地跑得通"
与"线上跑得通"是同一段代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

__all__ = ("AttachmentMeta",)


@dataclass(frozen=True)
class AttachmentMeta:
    """``path`` 是应用内相对路径；``modified_at`` 无值时为 ``None``。"""

    path: str
    size: int
    content_type: str | None = None
    modified_at: datetime | None = None
    #: 平台存储给的对象校验值；本地目录后端为空串。保留它只为让应用能做
    #: "变了没有"的判断，它不是可寻址的实现细节。
    etag: str = ""


def parse_modified_at(raw: object) -> datetime | None:
    """manager 给的是 ISO 8601 字符串；MinIO 无值时是空串。"""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None

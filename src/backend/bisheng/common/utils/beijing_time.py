# ruff: noqa: RUF002
"""东八区业务墙钟：专家问答 DATETIME 与库内 naive 存储对齐。

不依赖进程 TZ / MySQL time_zone。naive 表示 Asia/Shanghai 墙钟，不是 UTC。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def now_beijing() -> datetime:
    """当前东八区墙钟（naive），写入 DATETIME 用。"""
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def to_beijing_iso(value: datetime | None) -> str | None:
    """序列化成带 +08:00 的 ISO 串；naive 按东八墙钟解释。"""
    if value is None:
        return None
    if value.tzinfo is None:
        aware = value.replace(tzinfo=BEIJING_TZ)
    else:
        aware = value.astimezone(BEIJING_TZ)
    return aware.isoformat(timespec="seconds")


def beijing_epoch_seconds(value: datetime) -> int:
    """naive 东八墙钟转 epoch；避免容器 TZ=UTC 时 timestamp() 解错。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING_TZ)
    return int(value.timestamp())


def dump_qa_datetimes(value: Any) -> Any:
    """递归把 datetime 转成 +08:00 ISO；其余结构原样。"""
    if isinstance(value, datetime):
        return to_beijing_iso(value)
    if isinstance(value, dict):
        return {key: dump_qa_datetimes(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump_qa_datetimes(item) for item in value]
    return value

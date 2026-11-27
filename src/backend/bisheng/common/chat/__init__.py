from bisheng.common.chat.client import ChatClient
from bisheng.common.chat.types import IgnoreException, WorkType
from bisheng.common.chat.utils import (
    SourceType,
    judge_source,
    process_node_data,
    sync_judge_source,
)

__all__ = [
    "ChatClient",
    "ChatManager",
    "IgnoreException",
    "SourceType",
    "WorkType",
    "judge_source",
    "process_node_data",
    "sync_judge_source",
]


def __getattr__(name):
    if name == "ChatManager":
        from bisheng.common.chat.manager import ChatManager

        return ChatManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

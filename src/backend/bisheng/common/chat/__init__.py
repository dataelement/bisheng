from bisheng.common.chat.client import ChatClient
from bisheng.common.chat.types import IgnoreException, WorkType
from bisheng.common.chat.utils import (
    SourceType,
    extract_answer_keys,
    extract_answer_keys_async,
    judge_source,
    process_node_data,
    process_source_document,
    sync_judge_source,
    sync_process_source_document,
)

__all__ = [
    "ChatClient",
    "ChatManager",
    "IgnoreException",
    "WorkType",
    "SourceType",
    "extract_answer_keys",
    "extract_answer_keys_async",
    "judge_source",
    "process_node_data",
    "process_source_document",
    "sync_judge_source",
    "sync_process_source_document",
]


def __getattr__(name):
    if name == "ChatManager":
        from bisheng.common.chat.manager import ChatManager

        return ChatManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

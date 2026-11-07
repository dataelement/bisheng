"""The same per-file removal policy for move SQL and native index adapters."""

from bisheng.knowledge.domain.models.knowledge_file import FileSource

WEB_LINK_SYSTEM_KEYS = frozenset(
    {"source_type", "source_url", "final_url", "web_title", "imported_at", "html_snapshot_object_name"}
)


def effective_move_removed_fields(*, file_source: str | None, removed_fields: tuple[str, ...]) -> tuple[str, ...]:
    if type(removed_fields) is not tuple or any(type(name) is not str for name in removed_fields):
        raise ValueError("move field names must be a frozen tuple of strings")
    if file_source != FileSource.WEB_LINK.value:
        return removed_fields
    return tuple(name for name in removed_fields if name not in WEB_LINK_SYSTEM_KEYS)

from __future__ import annotations

from typing import Any


def normalize_file_sync_folder_path(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("folder path must be a string")
    segments = [segment.strip() for segment in value.replace("\\", "/").split("/") if segment.strip()]
    if not segments:
        return None
    for segment in segments:
        if segment in {".", ".."}:
            raise ValueError("folder path contains invalid segments")
        if len(segment) > 128:
            raise ValueError("folder path segment is too long")
    return "/".join(segments)


def split_file_sync_folder_path(value: str | None) -> list[str]:
    normalized = normalize_file_sync_folder_path(value)
    if normalized is None:
        return []
    return normalized.split("/")

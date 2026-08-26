"""Knowledge upload file-extension policy shared by platform upload and integrations."""

from __future__ import annotations

# Keep in sync with platform DropZone (`src/frontend/platform/.../DropZone.tsx`).
KNOWLEDGE_UPLOAD_CORE_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "txt",
        "docx",
        "ppt",
        "pptx",
        "md",
        "html",
        "htm",
        "xls",
        "xlsx",
        "csv",
        "doc",
        "wps",
        "et",
        "dps",
    }
)
KNOWLEDGE_UPLOAD_IMAGE_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "bmp"})
KNOWLEDGE_UPLOAD_MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        "mp3",
        "wav",
        "m4a",
        "aac",
        "flac",
        "ogg",
        "mp4",
        "mov",
        "avi",
        "mkv",
        "webm",
    }
)


class UnsupportedUploadFileExtensionError(ValueError):
    """Raised when a filename extension is outside the platform upload allowlist."""


def extract_upload_file_extension(file_name: str | None) -> str | None:
    name = str(file_name or "").strip()
    if not name or "/" in name or "\\" in name:
        return None
    if name.startswith(".") and name.count(".") == 1:
        return None
    base, ext = name.rsplit(".", 1)
    if not base or not ext:
        return None
    normalized = ext.strip().lower()
    return normalized or None


def resolve_knowledge_upload_extensions(*, image_parser_enabled: bool) -> frozenset[str]:
    allowed = set(KNOWLEDGE_UPLOAD_CORE_EXTENSIONS) | set(KNOWLEDGE_UPLOAD_MEDIA_EXTENSIONS)
    if image_parser_enabled:
        allowed |= set(KNOWLEDGE_UPLOAD_IMAGE_EXTENSIONS)
    return frozenset(allowed)


def validate_knowledge_upload_file_extension(
    file_name: str | None,
    *,
    image_parser_enabled: bool,
) -> None:
    extension = extract_upload_file_extension(file_name)
    allowed = resolve_knowledge_upload_extensions(image_parser_enabled=image_parser_enabled)
    if extension in allowed:
        return
    raise UnsupportedUploadFileExtensionError(extension or "")

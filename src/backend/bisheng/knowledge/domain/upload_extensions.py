"""Knowledge upload file-extension policy shared by platform upload and integrations."""

from __future__ import annotations

# Keep in sync with platform DropZone (`src/frontend/platform/.../DropZone.tsx`)
# and client knowledge upload (`src/frontend/client/.../knowledgeUtils.ts`).
KNOWLEDGE_UPLOAD_CORE_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "txt",
        "docx",
        "ppt",
        "pptx",
        "md",
        "xls",
        "xlsx",
        "doc",
        "html",
        "htm",
    }
)


class UnsupportedUploadFileExtensionError(ValueError):
    """Raised when a filename extension is outside the platform upload allowlist."""


def extract_upload_file_extension(file_name: str | None) -> str | None:
    name = str(file_name or "").strip()
    if not name:
        return None
    # MinIO presigned URLs are returned as upload file_path; strip query/fragment
    # before parsing so ".pdf?x-amz-algorithm=..." is treated as ".pdf".
    name = name.split("?", 1)[0].split("#", 1)[0].strip()
    if not name or "/" in name or "\\" in name:
        return None
    if name.startswith(".") and name.count(".") == 1:
        return None
    base, ext = name.rsplit(".", 1)
    if not base or not ext:
        return None
    normalized = ext.strip().lower()
    return normalized or None


def resolve_knowledge_upload_extensions(*, image_parser_enabled: bool = False) -> frozenset[str]:
    """Return the knowledge-space / filelib_sync upload allowlist.

    ``image_parser_enabled`` is kept for call-site compatibility; images are
    no longer accepted regardless of parser availability.
    """
    del image_parser_enabled
    return KNOWLEDGE_UPLOAD_CORE_EXTENSIONS


def validate_knowledge_upload_file_extension(
    file_name: str | None,
    *,
    image_parser_enabled: bool = False,
) -> None:
    extension = extract_upload_file_extension(file_name)
    allowed = resolve_knowledge_upload_extensions(image_parser_enabled=image_parser_enabled)
    if extension in allowed:
        return
    raise UnsupportedUploadFileExtensionError(extension or "")

"""Knowledge upload policy: accepted formats plus the composed per-file gate.

The drop zone filters by extension and size before anything is sent, but that
filter is a UX affordance, not an authorization boundary: registration accepts a
caller-supplied ``file_path`` and re-downloads the object, so the knowledge-space
staging entries and registration itself re-apply these rules against what is
actually stored.
"""

from bisheng.common.errcode.knowledge_space import SpaceFileFormatError
from bisheng.knowledge.domain.upload_file_size import (
    MEDIA_FILE_EXTENSIONS,
    get_file_extension,
    validate_knowledge_upload_file_size,
)

# Mirrors the client drop-zone allow-list (``knowledgeUtils.ALLOWED_EXTENSIONS``)
# and adds ``htm`` plus the media types the server accepts at the media limit.
# Every server-side producer stays inside this set: web links and media
# transcripts are ``.md``/``.html``, channel articles and conversation exports
# are ``.md``.
DOCUMENT_FILE_EXTENSIONS = frozenset(
    {
        "pdf",
        "ofd",
        "txt",
        "doc",
        "docx",
        "ppt",
        "pptx",
        "md",
        "html",
        "htm",
        "xls",
        "xlsx",
        "csv",
        "wps",
        "dps",
        "et",
    }
)
IMAGE_FILE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "bmp"})

SUPPORTED_FILE_EXTENSIONS = DOCUMENT_FILE_EXTENSIONS | IMAGE_FILE_EXTENSIONS | MEDIA_FILE_EXTENSIONS


def is_supported_upload_filename(filename: str | None) -> bool:
    extension = get_file_extension(filename)
    return bool(extension) and extension in SUPPORTED_FILE_EXTENSIONS


def validate_knowledge_upload_file_format(filename: str | None) -> None:
    """Reject an upload whose extension the pipeline cannot process."""
    if is_supported_upload_filename(filename):
        return
    extension = get_file_extension(filename)
    suffix = f".{extension}" if extension else "no extension"
    raise SpaceFileFormatError(msg=f"File format is not supported: {suffix}")


def validate_knowledge_upload_file(filename: str | None, size_bytes: int | None) -> None:
    """Both per-file rules, in the order a caller should see them fail."""
    validate_knowledge_upload_file_format(filename)
    validate_knowledge_upload_file_size(filename, size_bytes)

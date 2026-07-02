"""Knowledge-space upload file size limits (document vs media)."""

from bisheng.common.errcode.knowledge_space import SpaceFileSizeLimitError
from bisheng.common.services.config_service import settings

DEFAULT_UPLOADED_FILES_MAXIMUM_SIZE_MB = 50
DEFAULT_UPLOADED_MEDIA_MAXIMUM_SIZE_MB = 1

_AUDIO_FILE_EXTENSIONS = frozenset({'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'})
_VIDEO_FILE_EXTENSIONS = frozenset({'mp4', 'mov', 'avi', 'mkv', 'webm'})
MEDIA_FILE_EXTENSIONS = _AUDIO_FILE_EXTENSIONS | _VIDEO_FILE_EXTENSIONS


def get_file_extension(filename: str | None) -> str:
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[-1].lower()


def is_media_filename(filename: str | None) -> bool:
    return get_file_extension(filename) in MEDIA_FILE_EXTENSIONS


def get_upload_size_limits_mb() -> tuple[int, int]:
    env_conf = settings.get_from_db('env') or {}
    default_mb = int(
        env_conf.get('uploaded_files_maximum_size') or DEFAULT_UPLOADED_FILES_MAXIMUM_SIZE_MB
    )
    media_mb = int(
        env_conf.get('uploaded_media_maximum_size') or DEFAULT_UPLOADED_MEDIA_MAXIMUM_SIZE_MB
    )
    return default_mb, media_mb


def get_max_upload_bytes(filename: str | None) -> int:
    default_mb, media_mb = get_upload_size_limits_mb()
    limit_mb = media_mb if is_media_filename(filename) else default_mb
    return limit_mb * 1024 * 1024


def validate_knowledge_upload_file_size(filename: str | None, size_bytes: int | None) -> None:
    if size_bytes is None:
        return
    if size_bytes > get_max_upload_bytes(filename):
        raise SpaceFileSizeLimitError()

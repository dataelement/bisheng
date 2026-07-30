import asyncio
import os
import subprocess
import tempfile
import time
from io import BytesIO
from uuid import uuid4

from loguru import logger

from bisheng.core.storage.minio.minio_storage import MinioStorage

VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "mkv", "webm"})
MEDIA_UPLOAD_LOG_PREFIX = "[workstation.media_upload]"


class MediaUploadStageTimer:
    """Log per-stage latency for workstation media uploads (grep-friendly)."""

    def __init__(self, file_name: str, *, media_kind: str = "video", file_id: str | None = None):
        self.file_name = file_name
        self.media_kind = media_kind
        self.file_id = file_id
        self._started = time.monotonic()
        self._last = self._started
        self._current_stage = "start"
        logger.info(
            "{} START kind={} file={} file_id={}",
            MEDIA_UPLOAD_LOG_PREFIX,
            media_kind,
            file_name,
            file_id or "-",
        )

    def stage(self, name: str, **fields) -> None:
        self._current_stage = name
        now = time.monotonic()
        step_ms = (now - self._last) * 1000.0
        total_ms = (now - self._started) * 1000.0
        self._last = now
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info(
            "{} STAGE {} step_ms={:.1f} total_ms={:.1f} file={}{}",
            MEDIA_UPLOAD_LOG_PREFIX,
            name,
            step_ms,
            total_ms,
            self.file_name,
            f" {suffix}" if suffix else "",
        )

    def finish(self, **fields) -> None:
        total_ms = (time.monotonic() - self._started) * 1000.0
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info(
            "{} DONE total_ms={:.1f} file={}{}",
            MEDIA_UPLOAD_LOG_PREFIX,
            total_ms,
            self.file_name,
            f" {suffix}" if suffix else "",
        )

    def fail(self, exc: BaseException) -> None:
        total_ms = (time.monotonic() - self._started) * 1000.0
        logger.error(
            "{} FAIL stage={} total_ms={:.1f} file={} err={}",
            MEDIA_UPLOAD_LOG_PREFIX,
            self._current_stage,
            total_ms,
            self.file_name,
            exc,
        )


class WorkstationMediaCoverService:
    """Extract the first video keyframe and upload it as a MinIO cover image."""

    @classmethod
    def is_video_filename(cls, file_name: str) -> bool:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        return ext in VIDEO_EXTENSIONS

    @classmethod
    def write_temp_video(cls, content: bytes, file_name: str) -> str:
        suffix = os.path.splitext(file_name)[1] or ".mp4"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        with open(temp_path, "wb") as handle:
            handle.write(content)
        return temp_path

    @classmethod
    async def materialize_upload_to_temp(
        cls,
        upload_file,
        file_name: str,
        timer: MediaUploadStageTimer | None = None,
    ) -> str:
        """Stream an UploadFile to disk without loading the whole video into RAM."""
        suffix = os.path.splitext(file_name)[1] or ".mp4"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        await upload_file.seek(0)
        bytes_written = 0
        with open(temp_path, "wb") as handle:
            while chunk := await upload_file.read(1024 * 1024):
                handle.write(chunk)
                bytes_written += len(chunk)
        await upload_file.seek(0)
        if timer is not None:
            timer.stage("materialize_temp", bytes=bytes_written, temp_path=temp_path)
        return temp_path

    @classmethod
    def cleanup_temp(cls, *paths: str | None) -> None:
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    logger.warning("Failed to remove temp media cover file: {}", path)

    @classmethod
    def extract_first_keyframe_jpeg(cls, video_path: str, output_path: str) -> bool:
        command = [
            "ffmpeg",
            "-y",
            "-skip_frame",
            "nokey",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            output_path,
        ]
        try:
            subprocess.run(command, capture_output=True, check=True, timeout=60)
        except FileNotFoundError:
            logger.warning("ffmpeg is not installed; video cover extraction skipped")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg timed out while extracting video cover for {}", video_path)
            return False
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
            logger.warning("ffmpeg video cover extraction failed: {}", stderr[-1000:])
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0

    @classmethod
    def _read_cover_jpeg(cls, video_path: str) -> bytes | None:
        fd, cover_path = tempfile.mkstemp(suffix="_cover.jpg")
        os.close(fd)
        try:
            if not cls.extract_first_keyframe_jpeg(video_path, cover_path):
                return None
            with open(cover_path, "rb") as cover_file:
                return cover_file.read()
        finally:
            cls.cleanup_temp(cover_path)

    @classmethod
    async def upload_video_cover(
        cls,
        video_path: str,
        minio_client: MinioStorage,
        timer: MediaUploadStageTimer | None = None,
    ) -> str | None:
        cover_bytes = await asyncio.to_thread(cls._read_cover_jpeg, video_path)
        if timer is not None:
            timer.stage(
                "ffmpeg_cover",
                cover_bytes=len(cover_bytes) if cover_bytes else 0,
                video_path=video_path,
            )
        if not cover_bytes:
            return None

        cover_object = f"{uuid4().hex}_cover.jpg"
        await minio_client.put_object_tmp(
            object_name=cover_object,
            file=BytesIO(cover_bytes),
            content_type="image/jpeg",
        )
        if timer is not None:
            timer.stage("cover_minio_put", cover_object=cover_object)
        share_url = await minio_client.get_share_link(cover_object, bucket=minio_client.tmp_bucket)
        if timer is not None:
            timer.stage("cover_share_link")
        return minio_client.clear_minio_share_host(share_url)

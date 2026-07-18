from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from bisheng.common.errcode.portal_course import (
    PortalCourseMediaTooLargeError,
    PortalCourseMediaUnsupportedError,
    PortalCourseProbeFailedError,
    PortalCourseSourceReplaceError,
)

logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 1024 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_MAX_PROBE_OUTPUT_BYTES = 1024 * 1024
_MP4_BRANDS = {
    b"isom",
    b"iso2",
    b"iso3",
    b"iso4",
    b"iso5",
    b"iso6",
    b"mp41",
    b"mp42",
    b"avc1",
    b"dash",
    b"M4V ",
}


@dataclass(frozen=True)
class MediaProbe:
    extension: str
    content_type: str
    duration_seconds: int


@dataclass(frozen=True)
class UploadedMedia:
    object_name: str
    original_filename: str
    duration_seconds: int
    content_type: str
    provisional_job_id: str | None = None


class PortalCourseMediaService:
    """Streams uploads, validates their actual media, and persists to MinIO."""

    def __init__(
        self,
        *,
        storage,
        runner: Callable = subprocess.run,
        max_bytes: int = MAX_MEDIA_BYTES,
        temp_dir: str | Path | None = None,
        probe_timeout_seconds: int = 30,
    ):
        self.storage = storage
        self.runner = runner
        self.max_bytes = max_bytes
        self.temp_dir = Path(temp_dir) if temp_dir is not None else None
        self.probe_timeout_seconds = probe_timeout_seconds

    @staticmethod
    def ensure_size(size: int) -> None:
        if size > MAX_MEDIA_BYTES:
            raise PortalCourseMediaTooLargeError()

    @staticmethod
    def _detect_container(path: Path) -> str:
        with path.open("rb") as stream:
            header = stream.read(4096)
        if len(header) >= 12 and header[4:8] == b"ftyp":
            if header[8:12] not in _MP4_BRANDS:
                raise PortalCourseMediaUnsupportedError()
            return "mp4"
        if b"\x42\x82" in header and b"webm" in header.lower():
            return "webm"
        raise PortalCourseMediaUnsupportedError()

    def probe(self, path: str | Path) -> MediaProbe:
        media_path = Path(path)
        try:
            container = self._detect_container(media_path)
        except PortalCourseMediaUnsupportedError:
            raise
        except OSError as exc:
            logger.warning(
                "portal course media header read failed error_type=%s",
                type(exc).__name__,
            )
            raise PortalCourseProbeFailedError() from exc
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(media_path),
        ]
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.probe_timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning(
                "portal course ffprobe failed error_type=%s",
                type(exc).__name__,
            )
            raise PortalCourseProbeFailedError() from exc
        stdout = result.stdout or ""
        if result.returncode != 0 or len(stdout.encode("utf-8")) > _MAX_PROBE_OUTPUT_BYTES:
            raise PortalCourseProbeFailedError()
        try:
            payload = json.loads(stdout)
            format_data = payload["format"]
            format_names = {
                item.strip().lower()
                for item in str(format_data.get("format_name", "")).split(",")
                if item.strip()
            }
            duration = float(format_data["duration"])
            streams = payload["streams"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "portal course ffprobe response invalid error_type=%s",
                type(exc).__name__,
            )
            raise PortalCourseProbeFailedError() from exc
        if not math.isfinite(duration) or duration <= 0 or not isinstance(streams, list):
            raise PortalCourseProbeFailedError()

        video_codecs = [
            str(item.get("codec_name", "")).lower()
            for item in streams
            if item.get("codec_type") == "video"
        ]
        audio_codecs = [
            str(item.get("codec_name", "")).lower()
            for item in streams
            if item.get("codec_type") == "audio"
        ]
        known_streams = {"video", "audio"}
        if (
            len(video_codecs) != 1
            or any(item.get("codec_type") not in known_streams for item in streams)
        ):
            raise PortalCourseMediaUnsupportedError()

        if container == "mp4":
            if (
                "mp4" not in format_names
                or video_codecs != ["h264"]
                or any(codec != "aac" for codec in audio_codecs)
            ):
                raise PortalCourseMediaUnsupportedError()
        elif (
            "webm" not in format_names
            or video_codecs[0] not in {"vp8", "vp9"}
            or any(codec not in {"vorbis", "opus"} for codec in audio_codecs)
        ):
            raise PortalCourseMediaUnsupportedError()

        return MediaProbe(
            extension=container,
            content_type=f"video/{container}",
            duration_seconds=math.ceil(duration),
        )

    async def save_upload(
        self,
        upload,
        *,
        tenant_id: int,
        course_id: str,
        video_id: str,
        before_store: Callable[[str], Awaitable[str]] | None = None,
    ) -> UploadedMedia:
        temp_file = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="portal-course-",
            suffix=".upload",
            dir=self.temp_dir,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        total = 0
        try:
            with temp_file:
                while True:
                    chunk = await upload.read(_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise PortalCourseMediaTooLargeError()
                    temp_file.write(chunk)
            if self.max_bytes == MAX_MEDIA_BYTES:
                self.ensure_size(total)
            probe = self.probe(temp_path)
            object_name = (
                f"portal-course/{tenant_id}/{course_id}/{video_id}/"
                f"{uuid.uuid4().hex}.{probe.extension}"
            )
            try:
                provisional_job_id = (
                    await before_store(object_name) if before_store is not None else None
                )
                await self.storage.put_object(
                    bucket_name=self.storage.bucket,
                    object_name=object_name,
                    file=temp_path,
                    content_type=probe.content_type,
                )
            except Exception as exc:
                logger.warning(
                    "portal course media store failed tenant_id=%s course_id=%s "
                    "video_id=%s error_type=%s",
                    tenant_id,
                    course_id,
                    video_id,
                    type(exc).__name__,
                )
                raise PortalCourseSourceReplaceError() from exc
            original_name = os.path.basename(
                str(getattr(upload, "filename", "") or "video").replace("\\", "/")
            )[:255]
            return UploadedMedia(
                object_name=object_name,
                original_filename=original_name,
                duration_seconds=probe.duration_seconds,
                content_type=probe.content_type,
                provisional_job_id=provisional_job_id,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    async def get_play_url(self, object_name: str) -> str:
        return await self.storage.get_share_link(
            object_name,
            bucket=self.storage.bucket,
            clear_host=True,
            expire_days=1,
        )

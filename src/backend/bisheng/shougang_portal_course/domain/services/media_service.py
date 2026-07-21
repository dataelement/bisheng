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
_AUXILIARY_STREAM_TYPES = {"subtitle", "data", "attachment"}
_MP4_AUDIO_CODECS = {"aac", "mp3"}
_WEBM_VIDEO_CODECS = {"vp8", "vp9"}
_WEBM_AUDIO_CODECS = {"vorbis", "opus"}
_CODEC_DISPLAY_NAMES = {
    "aac": "AAC",
    "flac": "FLAC",
    "h264": "H.264",
    "hevc": "HEVC/H.265",
    "mp3": "MP3",
    "mpeg4": "MPEG-4 Visual",
    "opus": "Opus",
    "prores": "ProRes",
    "vorbis": "Vorbis",
    "vp8": "VP8",
    "vp9": "VP9",
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
    def _iso_bmff_major_brand(header: bytes) -> bytes | None:
        offset = 0
        while offset + 8 <= len(header):
            box_size = int.from_bytes(header[offset : offset + 4], "big")
            box_type = header[offset + 4 : offset + 8]
            box_header_size = 8
            if box_size == 1:
                if offset + 16 > len(header):
                    return None
                box_size = int.from_bytes(header[offset + 8 : offset + 16], "big")
                box_header_size = 16
            elif box_size == 0:
                box_size = len(header) - offset

            if box_size < box_header_size:
                return None
            if box_type == b"ftyp":
                brand_offset = offset + box_header_size
                if box_size < box_header_size + 8 or brand_offset + 4 > len(header):
                    return None
                return header[brand_offset : brand_offset + 4]
            if offset + box_size > len(header):
                return None
            offset += box_size
        return None

    @staticmethod
    def _detect_container(path: Path) -> str:
        with path.open("rb") as stream:
            header = stream.read(4096)
        major_brand = PortalCourseMediaService._iso_bmff_major_brand(header)
        if major_brand is not None:
            normalized_brand = major_brand.lower()
            if normalized_brand.startswith(b"3gp"):
                raise PortalCourseMediaUnsupportedError(msg="检测到 3GP 容器。仅支持 MP4 或 WebM")
            if normalized_brand.startswith(b"3g2"):
                raise PortalCourseMediaUnsupportedError(msg="检测到 3G2 容器。仅支持 MP4 或 WebM")
            return "mp4"
        if b"\x42\x82" in header and b"webm" in header.lower():
            return "webm"
        raise PortalCourseMediaUnsupportedError(msg="无法识别视频容器。仅支持 MP4 或 WebM")

    @staticmethod
    def _is_attached_picture(stream: dict) -> bool:
        disposition = stream.get("disposition")
        return isinstance(disposition, dict) and disposition.get("attached_pic") == 1

    @staticmethod
    def _codec_display_name(codec: str) -> str:
        known_name = _CODEC_DISPLAY_NAMES.get(codec)
        if known_name is not None:
            return known_name
        safe_name = "".join(
            char for char in codec if char.isascii() and (char.isalnum() or char in {"-", ".", "_", "+"})
        )[:32]
        return safe_name.upper() or "未知"

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
        if any(not isinstance(item, dict) for item in streams):
            raise PortalCourseProbeFailedError()

        primary_video_streams = [
            item for item in streams if item.get("codec_type") == "video" and not self._is_attached_picture(item)
        ]
        if not primary_video_streams:
            raise PortalCourseMediaUnsupportedError(msg="未检测到主视频轨")
        if len(primary_video_streams) > 1:
            raise PortalCourseMediaUnsupportedError(msg="检测到多个主视频轨。当前仅支持一个主视频轨")
        unsupported_stream_types = {
            str(item.get("codec_type", ""))
            for item in streams
            if item.get("codec_type") not in {"video", "audio", *_AUXILIARY_STREAM_TYPES}
        }
        if unsupported_stream_types:
            raise PortalCourseMediaUnsupportedError(msg="视频包含不支持的媒体轨类型")

        video_codec = str(primary_video_streams[0].get("codec_name", "")).lower()
        audio_codecs = [
            str(item.get("codec_name", "")).lower() for item in streams if item.get("codec_type") == "audio"
        ]

        if container == "mp4":
            if "mp4" not in format_names:
                raise PortalCourseMediaUnsupportedError(msg="检测到非 MP4 的 ISO-BMFF 容器。仅支持 MP4 或 WebM")
            if video_codec != "h264":
                display_name = self._codec_display_name(video_codec)
                raise PortalCourseMediaUnsupportedError(msg=f"检测到 {display_name} 视频编码。请转换为 H.264")
            unsupported_audio = next(
                (codec for codec in audio_codecs if codec not in _MP4_AUDIO_CODECS),
                None,
            )
            if unsupported_audio is not None:
                display_name = self._codec_display_name(unsupported_audio)
                raise PortalCourseMediaUnsupportedError(msg=f"检测到 {display_name} 音频编码。MP4 仅支持 AAC 或 MP3")
        else:
            if "webm" not in format_names:
                raise PortalCourseMediaUnsupportedError(msg="检测到非 WebM 容器。仅支持 MP4 或 WebM")
            if video_codec not in _WEBM_VIDEO_CODECS:
                display_name = self._codec_display_name(video_codec)
                raise PortalCourseMediaUnsupportedError(msg=f"检测到 {display_name} 视频编码。WebM 仅支持 VP8 或 VP9")
            unsupported_audio = next(
                (codec for codec in audio_codecs if codec not in _WEBM_AUDIO_CODECS),
                None,
            )
            if unsupported_audio is not None:
                display_name = self._codec_display_name(unsupported_audio)
                raise PortalCourseMediaUnsupportedError(
                    msg=f"检测到 {display_name} 音频编码。WebM 仅支持 Vorbis 或 Opus"
                )

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

import os
import subprocess
import tempfile
from uuid import uuid4

from loguru import logger

from bisheng.core.storage.minio.minio_storage import MinioStorage

VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "mkv", "webm"})


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
    async def upload_video_cover(cls, video_path: str, minio_client: MinioStorage) -> str | None:
        fd, cover_path = tempfile.mkstemp(suffix="_cover.jpg")
        os.close(fd)
        try:
            if not cls.extract_first_keyframe_jpeg(video_path, cover_path):
                return None

            cover_object = f"{uuid4().hex}_cover.jpg"
            with open(cover_path, "rb") as cover_file:
                await minio_client.put_object_tmp(
                    object_name=cover_object,
                    file=cover_file,
                    content_type="image/jpeg",
                )
            share_url = await minio_client.get_share_link(cover_object, bucket=minio_client.tmp_bucket)
            return minio_client.clear_minio_share_host(share_url)
        finally:
            cls.cleanup_temp(cover_path)

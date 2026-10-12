"""Hand knowledge-base images retrieved in this request to the code interpreter.

Retrieval returns images as ``/{bucket}/knowledge/images/{kb}/{file}/{name}``. The
browser resolves that through the frontend proxy; the code interpreter cannot, and it
must not reach object storage itself. So the backend process (which already holds the
MinIO client) writes the images into the run's working directory before the script
starts, and the retrieval result tells the model the relative path to open.

Only images that actually appeared in this request's retrieval results are ever
fetched. A path the model writes itself never reaches object storage.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

STAGE_DIR = "uploads/kb"
ANCHOR_LEFT = "\u27e6"  # ⟦
ANCHOR_RIGHT = "\u27e7"  # ⟧
DEFAULT_MAX_FILES = 100
# Total byte cap defaults to this many times the per-image cap.
TOTAL_BYTES_FACTOR = 5
_CHUNK = 64 * 1024

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_OBJECT_DIR = "knowledge/images"


@dataclass(frozen=True)
class StagedImage:
    object_key: str
    rel_path: str


class _SkipImage(Exception):
    """One image is not written; ``reason`` is shown to the model."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _fetch_failure_reason(exc: Exception) -> str:
    if getattr(exc, "code", "") in {"NoSuchKey", "NoSuchObject"}:
        return "not found in object storage"
    return "read from object storage failed"


class KbImageStage:
    """Request-scoped registry of knowledge-base images plus the code that writes them."""

    def __init__(
        self,
        bucket: str,
        *,
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int,
        max_total_bytes: int,
    ):
        self.bucket = bucket
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self._entries: dict[str, StagedImage] = {}
        self._lock = threading.Lock()
        self._path_re = re.compile(
            rf"^/{re.escape(bucket)}/({_OBJECT_DIR}/([0-9]+)/([0-9]+)/([^/?#\\\x00-\x1f]+))(?:[?#].*)?$"
        )

    @classmethod
    def from_settings(cls) -> KbImageStage:
        from bisheng.common.services.config_service import settings

        sandbox = settings.sandbox_conf
        per_file = int(sandbox.max_copy_in_bytes)
        explicit_total = int(sandbox.kb_image_stage_max_total_bytes)
        return cls(
            (settings.get_minio_conf().public_bucket or "bisheng").strip(),
            max_files=max(int(sandbox.kb_image_stage_max_files), 0),
            max_file_bytes=per_file,
            max_total_bytes=explicit_total if explicit_total > 0 else per_file * TOTAL_BYTES_FACTOR,
        )

    def __len__(self) -> int:
        return len(self._entries)

    def paths(self) -> list[str]:
        return [image.rel_path for image in list(self._entries.values())]

    def _parse(self, url: str) -> StagedImage | None:
        match = self._path_re.match(url.strip())
        if not match:
            return None
        object_key, kb_id, file_id, name = match.groups()
        if name in {".", ".."}:
            return None
        return StagedImage(object_key=object_key, rel_path=f"{STAGE_DIR}/{kb_id}/{file_id}/{name}")

    def register(self, url: str) -> StagedImage | None:
        image = self._parse(url)
        if image is None:
            return None
        with self._lock:
            self._entries.setdefault(image.rel_path, image)
        return image

    def annotate(self, chunk: str) -> str:
        """Register every stageable image in ``chunk`` and append its relative path after it.

        The original markdown is left untouched so the answer keeps rendering in the page.
        """

        def _replace(match: re.Match[str]) -> str:
            image = self.register(match.group(2))
            if image is None:
                return match.group(0)
            return f"{match.group(0)}{ANCHOR_LEFT}file: {image.rel_path}{ANCHOR_RIGHT}"

        return _MARKDOWN_IMAGE_RE.sub(_replace, chunk)

    def tool_hint(self) -> str:
        return (
            " KNOWLEDGE-BASE IMAGES: a search result may show an image followed by "
            f"`{ANCHOR_LEFT}file: uploads/kb/...{ANCHOR_RIGHT}`. That relative path is a real file in the "
            "working directory: pass it straight to `open()` or `add_picture()`. Do NOT download the "
            "image by URL and do NOT invent a host name; the original `/bisheng/...` link is only "
            "for display."
        )

    def failure_advisory(self, code: str) -> str:
        """Non-blocking hint when a failed script refers to knowledge-image URLs."""
        if not code or _OBJECT_DIR not in code:
            return ""
        example = self.paths()[:1]
        sample = f" (for example `{example[0]}`)" if example else ""
        return (
            "\n\nNOTE: this script refers to a knowledge-base image URL or `/bisheng/...` path, which cannot be "
            f"opened from the working directory. Use the relative path given after the image in the search "
            f"result as `{ANCHOR_LEFT}file: ...{ANCHOR_RIGHT}`{sample}."
        )

    def materialize(self, dir_path: str, client_factory: Callable[[], Any]) -> str:
        """Write the registered images under ``dir_path``.

        Returns a notice for the model naming every image that was not written and why;
        an empty string means everything registered is in place.
        """
        entries = list(self._entries.values())
        if not entries:
            return ""
        try:
            client = client_factory()
        except Exception:
            logger.warning("kb image stage: object storage client unavailable")
            return self._notice([(image.rel_path, "object storage is not available") for image in entries])

        root = os.path.realpath(dir_path)
        skipped: list[tuple[str, str]] = []
        written = 0
        total = 0
        for image in entries:
            if written >= self.max_files:
                skipped.append((image.rel_path, f"over the limit of {self.max_files} images per run"))
                continue
            dest = os.path.realpath(os.path.join(root, image.rel_path))
            if not dest.startswith(root + os.sep):
                skipped.append((image.rel_path, "invalid path"))
                continue
            if os.path.isfile(dest):
                # Already written by an earlier run that shares this directory.
                written += 1
                total += os.path.getsize(dest)
                continue
            try:
                size = self._download(client, image, dest, self.max_total_bytes - total)
            except _SkipImage as skip:
                skipped.append((image.rel_path, skip.reason))
                continue
            except Exception as exc:
                logger.warning("kb image stage: fetch failed key={} err={}", image.object_key, type(exc).__name__)
                skipped.append((image.rel_path, _fetch_failure_reason(exc)))
                continue
            written += 1
            total += size

        logger.info("kb image stage: written={} skipped={} bytes={}", written, len(skipped), total)
        return self._notice(skipped)

    def _download(self, client: Any, image: StagedImage, dest: str, remaining_total: int) -> int:
        response = client.get_object(self.bucket, image.object_key)
        tmp = f"{dest}.part"
        size = 0
        try:
            declared = (getattr(response, "headers", None) or {}).get("Content-Length")
            if declared and str(declared).isdigit():
                self._check_size(int(declared), remaining_total)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(tmp, "wb") as handle:
                for block in response.stream(_CHUNK):
                    size += len(block)
                    self._check_size(size, remaining_total)
                    handle.write(block)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        finally:
            response.close()
            response.release_conn()
        return size

    def _check_size(self, size: int, remaining_total: int) -> None:
        if size > self.max_file_bytes:
            raise _SkipImage(f"larger than the per-image limit of {self.max_file_bytes} bytes")
        if size > remaining_total:
            raise _SkipImage(f"would exceed the total limit of {self.max_total_bytes} bytes per run")

    @staticmethod
    def _notice(skipped: list[tuple[str, str]]) -> str:
        if not skipped:
            return ""
        lines = "\n".join(f"- {path}: {reason}" for path, reason in skipped)
        return (
            "\n\nNOTE: these knowledge-base images were NOT written to the working directory, "
            f"so the script cannot open them:\n{lines}"
        )

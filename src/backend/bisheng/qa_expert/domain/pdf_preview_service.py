"""问答 Office 附件复用无用户水印的持久化 PDF。"""

import hashlib
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from loguru import logger
from minio.error import S3Error

from bisheng.knowledge.pdf.artifact_builder import build_pdf_artifact
from bisheng.knowledge.pdf.converter import OFFICE_EXTENSIONS, ConversionContext, PdfConverterRegistry
from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf


class QaPdfPreviewGenerationError(RuntimeError):
    """基础 PDF 未能在受控生成窗口内准备完成。"""


class QaPdfPreviewService:
    """原文件先读取, 持久产物按源快照查找; 仅缓存缺失时使用 Redis。"""

    def __init__(
        self,
        *,
        storage: Any,
        redis_client: Any = None,
        converter_registry: PdfConverterRegistry | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.storage = storage
        self.redis_client = redis_client
        self.converter_registry = converter_registry or PdfConverterRegistry()
        self.timeout_seconds = timeout_seconds

    def _read_cached(self, object_name: str) -> bytes | None:
        try:
            content = self.storage.get_object_sync(object_name=object_name)
        except FileNotFoundError:
            return None
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return None
            raise
        if content is None:
            return None
        with TemporaryDirectory(prefix="qa-pdf-check-") as temporary_directory:
            candidate = Path(temporary_directory) / "cached.pdf"
            candidate.write_bytes(content)
            try:
                validate_pdf(candidate)
            except PdfValidationError:
                logger.warning("qa_pdf_cached_artifact_invalid object_name={}", object_name)
                return None
        return content

    def get_or_generate(
        self,
        *,
        source_bytes: bytes,
        filename: str,
        source_bucket: str,
        source_object: str,
        tenant_id: int | None,
    ) -> bytes:
        """在同一工作线程持锁到上传结束, 协程取消不会提前释放生成锁。"""
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in OFFICE_EXTENSIONS or not source_bytes:
            raise QaPdfPreviewGenerationError("unsupported or empty Office source")
        snapshot = json.dumps(
            ["v1", tenant_id, source_bucket, source_object, hashlib.sha256(source_bytes).hexdigest(), extension],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(snapshot.encode()).hexdigest()
        # 无租户上下文保持独立命名空间, 不擅自映射为租户 1。
        scope = str(int(tenant_id)) if tenant_id is not None else "unscoped"
        object_name = f"knowledge/pdf-artifacts/qa/{scope}/{digest}.pdf"
        cached = self._read_cached(object_name)
        if cached is not None:
            return cached

        if self.redis_client is None:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            self.redis_client = get_redis_client_sync().connection
        deadline = time.monotonic() + self.timeout_seconds
        lock = self.redis_client.lock(
            f"bisheng:qa_pdf_artifact:generation:{scope}:{digest}",
            timeout=max(300, self.timeout_seconds + 60),
            blocking_timeout=self.timeout_seconds,
        )
        with lock:
            cached = self._read_cached(object_name)
            if cached is not None:
                return cached
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                raise QaPdfPreviewGenerationError("PDF generation deadline exceeded")

            def require_ownership() -> None:
                if not lock.owned() or time.monotonic() >= deadline:
                    raise QaPdfPreviewGenerationError("PDF generation lease or deadline expired")

            with TemporaryDirectory(prefix="qa-pdf-artifact-") as temporary_directory:
                root = Path(temporary_directory)
                source_path = root / f"source.{extension}"
                source_path.write_bytes(source_bytes)
                built = build_pdf_artifact(
                    source_path=source_path,
                    output_directory=root / "output",
                    object_name=object_name,
                    storage=self.storage,
                    converter_registry=self.converter_registry,
                    conversion_context=ConversionContext(timeout_seconds=remaining),
                    before_upload=require_ownership,
                )
                logger.info("qa_pdf_artifact_generated tenant_id={} artifact={}", tenant_id, digest)
                return built.pdf_path.read_bytes()

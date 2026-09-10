"""知识库与业务附件共用的 PDF 生成、校验及持久化。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bisheng.knowledge.pdf.converter import ConversionContext, PdfConverterRegistry
from bisheng.knowledge.pdf.validator import PdfValidationResult, validate_pdf


@dataclass(frozen=True)
class BuiltPdfArtifact:
    pdf_path: Path
    validation: PdfValidationResult


def build_pdf_artifact(
    *,
    source_path: Path,
    output_directory: Path,
    object_name: str,
    storage: Any,
    converter_registry: PdfConverterRegistry,
    conversion_context: ConversionContext,
    before_upload: Callable[[], None] | None = None,
) -> BuiltPdfArtifact:
    """只保存通过完整校验的基础 PDF; 调用方负责状态归属与临时目录。"""
    output_directory.mkdir(parents=True, exist_ok=True)
    conversion = converter_registry.convert(source_path, output_directory, conversion_context)
    validation = validate_pdf(conversion.pdf_path)
    if before_upload is not None:
        before_upload()
    storage.put_object_sync(
        object_name=object_name,
        file=conversion.pdf_path,
        content_type="application/pdf",
    )
    return BuiltPdfArtifact(conversion.pdf_path, validation)

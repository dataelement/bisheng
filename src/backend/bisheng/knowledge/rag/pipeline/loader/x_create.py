import os
from typing import List

from langchain_core.documents import Document

from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.ppt import BishengPptLoader
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (
    _convert_file_extension,
)
from bisheng.knowledge.rag.pipeline.loader.word import BishengWordLoader


class XinChuangFormatterLoader(BaseBishengLoader):
    """Convert xinchuang office formats to standard office formats before parsing."""

    FORMAT_MAP = {
        "wps": ("docx", "word"),
        "et": ("xlsx", "excel"),
        "dps": ("pptx", "ppt"),
    }

    def __init__(
            self,
            retain_images: bool = True,
            header_rows: List[int] | None = None,
            data_rows: int = 12,
            append_header: bool = True,
            *args,
            **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.retain_images = retain_images
        self.header_rows = header_rows or [0, 1]
        self.data_rows = data_rows
        self.append_header = append_header

    def load(self) -> List[Document]:
        target_ext, loader_type = self.FORMAT_MAP.get(self.file_extension, (None, None))
        if not target_ext or not loader_type:
            raise KnowledgeFileNotSupportedError()

        converted_path = self._convert_with_libreoffice(target_ext)
        delegated_loader = self._build_delegate_loader(converted_path, target_ext, loader_type)
        documents = delegated_loader.load()

        self.local_image_dir = delegated_loader.local_image_dir
        self.bbox_list = delegated_loader.bbox_list
        if self.file_extension in ["wps", "et"]:
            self.preview_file_path = converted_path
        else:
            self.preview_file_path = delegated_loader.preview_file_path
        return documents

    def _convert_with_libreoffice(self, target_ext: str) -> str:
        converted_path = _convert_file_extension(
            input_path=self.file_path,
            convert_extension=target_ext,
            output_dir=self.tmp_dir,
            except_file_ext=target_ext,
        )
        if not converted_path or not os.path.exists(converted_path):
            raise RuntimeError(f"failed to convert {self.file_name} to {target_ext}")
        return converted_path

    def _build_delegate_loader(
            self, file_path: str, file_extension: str, loader_type: str
    ) -> BaseBishengLoader:
        params = {
            "file_path": file_path,
            "file_metadata": self.file_metadata,
            "file_extension": file_extension,
            "tmp_dir": self.tmp_dir,
        }
        if loader_type == "word":
            return BishengWordLoader(**params, retain_images=self.retain_images)
        if loader_type == "excel":
            return ExcelLoader(
                **params,
                header_rows=self.header_rows,
                data_rows=self.data_rows,
                append_header=self.append_header,
            )
        if loader_type == "ppt":
            return BishengPptLoader(**params, retain_images=self.retain_images)
        raise KnowledgeFileNotSupportedError()

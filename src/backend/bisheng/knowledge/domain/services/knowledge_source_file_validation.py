"""接口原件的保守校验; 未知错误和基础设施错误不作为删除依据。"""

import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import fitz
from xlrd.compdoc import CompDoc, CompDocError

from bisheng.common.errcode.knowledge import KnowledgeSourceFileUnreadableError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

_OFFICE_ROOTS = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MAX_VALIDATION_BYTES = 128 * 1024 * 1024
_MAX_PACKAGE_ENTRIES = 10000


def is_sync_file(file: KnowledgeFile) -> bool:
    metadata = file.user_metadata or {}
    if not isinstance(metadata, dict):
        return False
    token_id = metadata.get("developer_token_id")
    return bool(metadata.get("filelib_sync_endpoint")) and type(token_id) is int and token_id > 0


def unreadable_reason(file: KnowledgeFile) -> str | None:
    if file.status != 3 or not is_sync_file(file):
        return None
    try:
        failure = json.loads(file.remark or "{}")
        if failure.get("status_code") == KnowledgeSourceFileUnreadableError.Code:
            reason = failure.get("data", {}).get("reason")
            if reason in {"encrypted", "damaged"}:
                return reason
    except (ValueError, TypeError, AttributeError):
        return None
    return None


def _unreadable(reason: str) -> None:
    raise KnowledgeSourceFileUnreadableError(reason=reason)


def validate_sync_original(path: str, file: KnowledgeFile) -> None:
    if not is_sync_file(file):
        return
    extension = file.file_name.rsplit(".", 1)[-1].lower()
    if extension == "pdf":
        try:
            with fitz.open(path) as document:
                if document.needs_pass or document.is_encrypted:
                    _unreadable("encrypted")
                if document.page_count <= 0:
                    _unreadable("damaged")
        except (fitz.FileDataError, fitz.EmptyFileError) as exc:
            raise KnowledgeSourceFileUnreadableError(reason="damaged") from exc
    elif extension in {*_OFFICE_ROOTS, "doc", "xls", "ppt"}:
        _validate_office(Path(path), extension)


def _validate_office(path: Path, extension: str) -> None:
    # 超出校验预算时仍走原有解析器, 不能把资源限制误判成文件损坏。
    if path.stat().st_size > _MAX_VALIDATION_BYTES:
        return
    with path.open("rb") as source:
        signature = source.read(8)
    if signature == _OLE_SIGNATURE:
        # 复用现有 xlrd 的 OLE 目录读取, 不引入额外解析依赖。
        try:
            container = CompDoc(path.read_bytes(), logfile=io.StringIO())
            if (
                container.get_named_stream("EncryptionInfo") is not None
                and container.get_named_stream("EncryptedPackage") is not None
            ):
                _unreadable("encrypted")
            if extension in _OFFICE_ROOTS:
                # 标准现代 Office 应为 ZIP, OLE 只能在已识别的加密包装下成立。
                _unreadable("damaged")
            if extension == "xls":
                import xlrd

                try:
                    with xlrd.open_workbook(filename=str(path), on_demand=True):
                        pass
                except xlrd.XLRDError as exc:
                    if str(exc) == "Workbook is encrypted":
                        raise KnowledgeSourceFileUnreadableError(reason="encrypted") from exc
                    # 其他工作簿错误可能是能力限制, 仍交给既有解析器。
        except CompDocError as exc:
            raise KnowledgeSourceFileUnreadableError(reason="damaged") from exc
        return
    if extension not in _OFFICE_ROOTS:
        # 老 Office 和第三方兼容格式无法可靠判定时保留原记录。
        return
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if any(item.flag_bits & 1 for item in entries):
                _unreadable("encrypted")
            if len(entries) > _MAX_PACKAGE_ENTRIES or sum(item.file_size for item in entries) > _MAX_VALIDATION_BYTES:
                return
            if archive.testzip() is not None:
                _unreadable("damaged")
            root = _OFFICE_ROOTS[extension]
            if root not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                _unreadable("damaged")
            for name in (root, "[Content_Types].xml"):
                with archive.open(name) as source:
                    for _, element in ElementTree.iterparse(source, events=("end",)):
                        element.clear()
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise KnowledgeSourceFileUnreadableError(reason="damaged") from exc

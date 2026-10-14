# ruff: noqa: RUF001
"""门户附件错误的安全分类与实际处理来源。"""

import errno
import json
import os
import socket
import ssl
from contextvars import ContextVar

import httpx
import requests

from bisheng.common.errcode.base import BaseErrorCode

attachment_context: ContextVar[dict | None] = ContextVar("attachment_context", default=None)
SOURCE_NAMES = {
    "etl4lm": "ETL4LM",
    "mineru": "MinerU",
    "paddle_ocr": "PaddleOCR",
    "local_pdf": "本地 PDF 解析",
    "local_word": "本地 Word 解析",
    "local_excel": "本地表格解析",
    "local_ppt": "本地 PPT 解析",
    "local_text": "本地文本解析",
    "local_html": "本地 HTML 解析",
    "libreoffice": "LibreOffice 格式转换",
    "pandoc": "Pandoc 文档转换",
    "attachment_reference": "附件引用校验",
    "attachment_download": "附件下载",
    "text_chunking": "正文切分",
    "attachment_upload": "附件上传",
    "unknown": "解析来源未识别",
    "visual_image": "视觉图片读取",
}
LOADER_SOURCES = {
    "Etl4lmLoader": "etl4lm",
    "MineruLoader": "mineru",
    "PaddleOcrLoader": "paddle_ocr",
    "LocalPdfLoader": "local_pdf",
    "BishengWordLoader": "local_word",
    "HierarchicalWordLoader": "local_word",
    "ExcelLoader": "local_excel",
    "BishengPptLoader": "local_ppt",
    "BishengTextLoader": "local_text",
    "HierarchicalMarkdownLoader": "local_text",
    "BishengHtmlLoader": "local_html",
    "XinChuangFormatterLoader": "libreoffice",
}


def mark_attachment_source(provider: str, stage: str = "parse") -> None:
    state = attachment_context.get()
    if state is not None:
        state.update(provider=provider, stage=stage)
        state.pop("operation", None)


def mark_attachment_loader(loader) -> None:
    mark_attachment_source(LOADER_SOURCES.get(type(loader).__name__, "unknown"))


class AttachmentQuestionError(BaseErrorCode):
    Code = 12050
    Msg = "附件未全部处理成功，本轮未生成回答"

    def __init__(self, errors: list[dict]):
        super().__init__(attachment_errors=errors)
        self.attachment_errors = errors


def _causes(error: Exception):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__ or getattr(error, "exception", None)


def attachment_error(
    state: dict, error: Exception | None = None, *, code: str = "", reason: str = "", suggestion: str = ""
) -> dict:
    provider = state.get("provider", "unknown")
    stage = state.get("stage", "parse")
    http_status = getattr(error, "http_status", None)
    causes = list(_causes(error)) if error is not None else []
    for cause in causes:
        response = getattr(cause, "response", None)
        if http_status is None and response is not None:
            http_status = getattr(response, "status_code", None)
    operation = getattr(error, "operation", None) or state.get("operation")
    if not code:
        suggestion = "请重试；持续失败请联系管理员。"
        if stage == "download":
            code, reason = "DOWNLOAD_FAILED", "附件下载失败，未能取得文件内容。"
            if any(
                isinstance(e, FileNotFoundError) or getattr(e, "code", None) in {"NoSuchKey", "NoSuchObject"}
                for e in causes
            ):
                reason = "临时文件不存在或已失效。"
            elif any(getattr(e, "code", None) == "NoSuchBucket" for e in causes):
                reason = "附件临时存储位置不存在。"
            elif http_status == 404:
                reason = "附件下载地址不存在或已失效。"
            elif http_status in {401, 403} or any(getattr(e, "code", None) == "AccessDenied" for e in causes):
                reason = "文件存储服务拒绝读取该附件。"
            elif any(isinstance(e, (TimeoutError, requests.Timeout, httpx.TimeoutException)) for e in causes):
                code, reason = "DOWNLOAD_TIMEOUT", "附件下载超时，未取得文件内容。"
            suggestion = "请重新上传附件后提问。"
        elif provider == "visual_image":
            code, reason = "IMAGE_READ_FAILED", "图片文件读取失败，未能准备模型图片输入。"
            suggestion = "请重新上传图片后再提问。"
        elif provider in {"libreoffice", "pandoc"}:
            code, reason = "CONVERSION_FAILED", "文档格式转换失败。"
            suggestion = "请另存为标准格式后重新上传。"
            if (
                any(isinstance(e, (TimeoutError, requests.Timeout, httpx.TimeoutException)) for e in causes)
                or operation == "timeout"
            ):
                code, reason = "CONVERSION_TIMEOUT", "文档格式转换超时。"
            elif operation == "tool_missing":
                code, reason = "CONVERSION_TOOL_MISSING", "格式转换工具未安装或不可用。"
                suggestion = "请联系管理员检查转换工具。"
        elif any(isinstance(e, (requests.ConnectTimeout, httpx.ConnectTimeout)) for e in causes):
            code, reason = "PARSER_CONNECT_TIMEOUT", "连接解析服务超时。"
        elif any(isinstance(e, (requests.ReadTimeout, httpx.ReadTimeout)) for e in causes):
            code, reason = "PARSER_READ_TIMEOUT", "解析服务未在规定时间内返回结果。"
            suggestion = "请稍后重试或拆分文件。"
        elif (
            any(isinstance(e, (TimeoutError, requests.Timeout, httpx.TimeoutException)) for e in causes)
            or operation == "timeout"
        ):
            code, reason = "PARSER_TIMEOUT", "解析服务请求超时，未能确定超时环节。"
        elif any(isinstance(e, ConnectionResetError) for e in causes):
            code, reason = "PARSER_CONNECTION_INTERRUPTED", "与解析服务的连接中断。"
        elif any(isinstance(e, (requests.ConnectionError, httpx.ConnectError, ConnectionError)) for e in causes):
            code, reason = "PARSER_CONNECT_FAILED", "无法连接解析服务。"
            if any(isinstance(e, socket.gaierror) for e in causes):
                reason = "解析服务地址解析失败。"
            elif any(isinstance(e, (ssl.SSLError, requests.exceptions.SSLError)) for e in causes):
                reason = "解析服务证书校验失败。"
            elif any(isinstance(e, OSError) and e.errno == errno.ECONNREFUSED for e in causes):
                reason = "解析服务拒绝建立连接。"
        elif any(
            isinstance(
                e,
                (
                    httpx.ReadError,
                    httpx.WriteError,
                    httpx.RemoteProtocolError,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
            for e in causes
        ):
            code, reason = "PARSER_CONNECTION_INTERRUPTED", "与解析服务的连接中断。"
        elif http_status is not None:
            statuses = {
                401: ("PARSER_AUTH_REJECTED", "解析服务认证失败，请联系管理员检查服务授权。"),
                403: ("PARSER_AUTH_REJECTED", "解析服务拒绝访问，请联系管理员检查服务授权。"),
                404: ("PARSER_ENDPOINT_NOT_FOUND", "解析接口不存在，请联系管理员检查服务地址和版本。"),
                413: ("PARSER_REQUEST_REJECTED", "文件超过解析服务允许的大小。"),
                415: ("PARSER_REQUEST_REJECTED", "解析服务不支持该文件格式。"),
                400: ("PARSER_REQUEST_REJECTED", "解析服务拒绝了该请求。"),
                422: ("PARSER_REQUEST_REJECTED", "解析请求不符合服务要求。"),
                429: ("PARSER_BUSY", "解析服务请求过多，请稍后重试。"),
                500: ("PARSER_SERVER_ERROR", "解析服务内部错误。"),
                503: ("PARSER_UNAVAILABLE", "解析服务暂不可用。"),
                502: ("PARSER_GATEWAY_ERROR", "解析服务网关异常。"),
                504: ("PARSER_GATEWAY_ERROR", "解析服务网关等待上游结果超时。"),
            }
            default = (
                ("PARSER_SERVER_ERROR", "解析服务返回服务端错误。")
                if http_status >= 500
                else ("PARSER_RESPONSE_INVALID", "解析服务返回了非预期的响应状态。")
            )
            code, reason = statuses.get(http_status, default)
            reason += f"（HTTP {http_status}）"
        elif operation == "request":
            code, reason = "PARSER_REQUEST_BUILD_FAILED", "解析请求参数构建失败。"
            suggestion = "请联系管理员检查解析器调用参数。"
        elif operation == "response" or any(isinstance(e, json.JSONDecodeError) for e in causes):
            code, reason = "PARSER_RESPONSE_INVALID", "解析服务返回的数据格式异常。"
        elif operation == "task":
            code, reason = "PARSER_TASK_FAILED", "解析服务返回任务失败，未提供可识别的具体原因。"
        elif any(type(e).__name__ == "FileDataError" for e in causes):
            code, reason = "FILE_DAMAGED", "文件结构损坏，无法解析。"
            suggestion = "请检查原文件后重新上传。"
        elif getattr(error, "code", None) == 10912:
            provider, stage = "text_chunking", "chunk"
            code, reason = "CHUNK_TOO_LARGE", "正文切分结果超过系统字符上限。"
        elif getattr(error, "code", None) == 10911:
            code, reason = "PARSER_CONTENT_EMPTY", "未提取到可用于问答的文本，该附件未用于回答。"
        elif getattr(error, "code", None) == 10914:
            code, reason = "TYPE_UNSUPPORTED", "当前解析能力不支持该附件，该附件已跳过。"
            if provider == "local_pdf" and str(state.get("filename", "")).rsplit(".", 1)[-1].lower() in {
                "png",
                "jpg",
                "jpeg",
                "bmp",
            }:
                code, reason = (
                    "IMAGE_PARSER_UNAVAILABLE",
                    "当前模型无法直接读取该图片，且未配置适用的图片文字识别服务，该附件已跳过。",
                )
                suggestion = "请选择支持图片的模型，或联系管理员配置图片解析服务。"
        else:
            code, reason = "PARSE_FAILED", "附件解析失败，未能识别具体原因。"
    filename = os.path.basename(str(state.get("filename") or "附件").replace("\\", "/"))[:200]
    return {
        "filename": filename,
        "file_id": str(state.get("file_id") or "")[:100],
        "temp_file_id": str(state.get("temp_file_id") or "")[:100],
        "provider": provider if provider in SOURCE_NAMES else "unknown",
        "source_type": "external"
        if provider in {"etl4lm", "mineru", "paddle_ocr"}
        else "tool"
        if provider in {"libreoffice", "pandoc"}
        else "local"
        if provider.startswith("local_")
        else "system",
        "http_status": http_status,
        "source": SOURCE_NAMES.get(provider, SOURCE_NAMES["unknown"]),
        "stage": stage,
        "code": f"ATTACHMENT_{code}",
        "reason": reason,
        "suggestion": suggestion,
    }

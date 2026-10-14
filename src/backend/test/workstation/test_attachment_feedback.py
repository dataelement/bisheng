"""附件来源、服务错误及部分失败的回归。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import requests

from bisheng.common.errcode.attachment import AttachmentQuestionError, attachment_context, attachment_error
from bisheng.common.stream_errors import stream_error_payload
from bisheng.utils.exceptions import EtlException


@pytest.mark.parametrize(
    "error,code",
    [
        (requests.ConnectTimeout("secret-url"), "PARSER_CONNECT_TIMEOUT"),
        (requests.ReadTimeout("secret-url"), "PARSER_READ_TIMEOUT"),
        (requests.ConnectionError("secret-url"), "PARSER_CONNECT_FAILED"),
        (httpx.ReadError("secret-url"), "PARSER_CONNECTION_INTERRUPTED"),
        (EtlException("private-response", http_status=401), "PARSER_AUTH_REJECTED"),
        (EtlException("private-response", http_status=404), "PARSER_ENDPOINT_NOT_FOUND"),
        (EtlException("private-response", http_status=413), "PARSER_REQUEST_REJECTED"),
        (EtlException("private-response", http_status=429), "PARSER_BUSY"),
        (EtlException("private-response", http_status=500), "PARSER_SERVER_ERROR"),
        (EtlException("private-response", http_status=503), "PARSER_UNAVAILABLE"),
        (EtlException("private-response", http_status=504), "PARSER_GATEWAY_ERROR"),
        (EtlException("private-response", operation="response"), "PARSER_RESPONSE_INVALID"),
        (EtlException("private-response", operation="task"), "PARSER_TASK_FAILED"),
    ],
)
def test_service_failure_keeps_provider_and_safe_cause(error, code):
    result = attachment_error({"filename": "报告.pdf", "provider": "etl4lm", "stage": "parse"}, error)
    payload = stream_error_payload(AttachmentQuestionError([result]), stage="document")
    assert result["code"] == "ATTACHMENT_" + code
    assert result["source"] == "ETL4LM"
    assert "secret-url" not in str(payload) and "private-response" not in str(payload)
    assert payload["attachment_errors"] == [result]
    assert payload["kind"] == "document"


@pytest.mark.parametrize("failure", ["empty", "missing", "parse"])
async def test_mixed_attachments_fail_as_a_group(monkeypatch, failure):
    from bisheng.workstation.domain.services import chat_service

    async def download(path):
        return path, path.rsplit("/", 1)[-1]

    async def parse(**kwargs):
        state = attachment_context.get()
        state["provider"] = "local_excel" if kwargs["file_name"].endswith("xlsx") else "etl4lm"
        if kwargs["file_name"] == "bad.xlsx":
            if failure == "parse":
                raise requests.ReadTimeout("private-server")
            return " "
        return "正文"

    monkeypatch.setattr(chat_service, "async_file_download", download)
    monkeypatch.setattr(chat_service, "get_file_content", parse)
    files = [
        {"filename": "ok.pdf", "filepath": "/ok.pdf"},
        {"filename": "bad.xlsx", "filepath": "" if failure == "missing" else "/bad.xlsx"},
    ]
    states = []
    with pytest.raises(AttachmentQuestionError) as caught:
        await chat_service._process_agent_files(
            SimpleNamespace(files=files),
            SimpleNamespace(visual=False),
            SimpleNamespace(user_id=1),
            SimpleNamespace(maxTokens=1000),
            portal_context=True,
            attachment_states=states,
        )
    assert len(caught.value.attachment_errors) == 1
    assert caught.value.attachment_errors[0]["filename"] == "bad.xlsx"
    assert states[0]["status"] == "success" and states[1]["status"] == "failed"
    assert "private-server" not in str(caught.value.attachment_errors)
    assert attachment_context.get() is None


@pytest.mark.parametrize("empty", [False, True])
async def test_visual_images_need_no_text_and_empty_images_stop(monkeypatch, empty):
    from bisheng.workstation.domain.services import chat_service

    monkeypatch.setattr(chat_service, "async_file_download", AsyncMock(return_value=("/image.png", "image.png")))
    monkeypatch.setattr(
        chat_service,
        "read_image_as_data_url",
        AsyncMock(return_value="data:image/png;base64," if empty else "data:image/png;base64,AA"),
    )
    parse = AsyncMock(side_effect=AssertionError("视觉图片无需提取正文"))
    monkeypatch.setattr(chat_service, "get_file_content", parse)
    if empty:
        with pytest.raises(AttachmentQuestionError) as caught:
            await chat_service._process_agent_files(
                SimpleNamespace(files=[{"filepath": "/image.png"}]),
                SimpleNamespace(visual=True),
                SimpleNamespace(user_id=1),
                SimpleNamespace(maxTokens=1000),
                portal_context=True,
            )
        assert caught.value.attachment_errors[0]["code"] == "ATTACHMENT_IMAGE_EMPTY"
    else:
        result = await chat_service._process_agent_files(
            SimpleNamespace(files=[{"filepath": "/image.png"}]),
            SimpleNamespace(visual=True),
            SimpleNamespace(user_id=1),
            SimpleNamespace(maxTokens=1000),
            portal_context=True,
        )
        assert result == ("", ["data:image/png;base64,AA"])
    parse.assert_not_awaited()


@pytest.mark.parametrize(
    "provider,expected",
    [("etl4lm", "ETL4LM"), ("mineru", "MinerU"), ("paddle_ocr", "PaddleOCR"), ("fallback", "本地 PDF 解析")],
)
async def test_real_pipeline_reports_selected_loader_and_rejects_empty(monkeypatch, tmp_path, provider, expected):
    from bisheng.common.services.config_service import settings
    from bisheng.knowledge.domain.models.knowledge_file import ParseType
    from bisheng.knowledge.rag.pipeline.loader import etl4lm, mineru, paddle_ocr, pdf
    from bisheng.user.domain.models.user import UserDao
    from bisheng.workstation.domain.services.chat_service import get_file_content

    types = {
        "etl4lm": ParseType.ETL4LM.value,
        "mineru": ParseType.MINERU.value,
        "paddle_ocr": ParseType.PADDLE_OCR.value,
    }
    conf = SimpleNamespace(
        chunking=SimpleNamespace(max_chunk_chars=10000),
        loader_provider=types.get(provider, ParseType.ETL4LM.value),
        etl4lm=SimpleNamespace(
            url="" if provider == "fallback" else "http://unused",
            model_dump=lambda: {"url": "http://unused", "ocr_sdk_url": ""},
        ),
        mineru=SimpleNamespace(url="http://unused", model_dump=lambda: {"url": "http://unused"}),
        paddle_ocr=SimpleNamespace(url="http://unused", model_dump=lambda: {"url": "http://unused"}),
    )
    monkeypatch.setattr(settings, "get_knowledge", lambda: conf)
    monkeypatch.setattr(UserDao, "get_user", lambda _: SimpleNamespace(user_name="test"))
    for cls in (etl4lm.Etl4lmLoader, mineru.MineruLoader, paddle_ocr.PaddleOcrLoader, pdf.LocalPdfLoader):
        monkeypatch.setattr(cls, "load", lambda self: [])
    state = {"filename": "empty.pdf", "provider": "unknown", "stage": "parse"}
    token = attachment_context.set(state)
    try:
        with pytest.raises(AttachmentQuestionError) as caught:
            await get_file_content(str(tmp_path / "empty.pdf"), "empty.pdf", 1)
        assert caught.value.attachment_errors[0]["source"] == expected
        assert caught.value.attachment_errors[0]["code"] == "ATTACHMENT_PARSER_CONTENT_EMPTY"
    finally:
        attachment_context.reset(token)


@pytest.mark.parametrize("cause", [requests.ConnectTimeout, requests.ReadTimeout])
def test_etl_adapter_retains_original_timeout(monkeypatch, tmp_path, cause):
    from bisheng.knowledge.rag.pipeline.loader import etl4lm

    file = tmp_path / "a.pdf"
    file.write_bytes(b"pdf")
    loader = etl4lm.Etl4lmLoader(
        url="http://unused",
        ocr_sdk_url="",
        file_path=str(file),
        file_metadata={},
        file_extension="pdf",
        tmp_dir=str(tmp_path),
    )

    def post(*args, **kwargs):
        raise cause("private-server")

    monkeypatch.setattr(etl4lm.requests, "post", post)
    with pytest.raises(EtlException) as caught:
        loader.load()
    assert isinstance(caught.value.__cause__, cause)
    assert str(caught.value) == "etl4lm server timeout"


@pytest.mark.parametrize("provider,status", [("etl4lm", 401), ("paddle_ocr", 503), ("mineru", 500)])
def test_real_service_adapter_http_status_preserved(monkeypatch, tmp_path, provider, status):
    from bisheng.knowledge.rag.pipeline.loader import etl4lm, mineru, paddle_ocr

    file = tmp_path / "a.pdf"
    file.write_bytes(b"pdf")
    params = {
        "url": "http://unused",
        "file_path": str(file),
        "file_metadata": {},
        "file_extension": "pdf",
        "tmp_dir": str(tmp_path),
    }
    classes = {"etl4lm": etl4lm.Etl4lmLoader, "paddle_ocr": paddle_ocr.PaddleOcrLoader, "mineru": mineru.MineruLoader}
    if provider == "etl4lm":
        params["ocr_sdk_url"] = ""
    loader = classes[provider](**params)
    response = requests.Response()
    response.status_code = status
    response._content = b"private-body"
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    state = {"filename": "a.pdf", "provider": provider, "stage": "parse"}
    token = attachment_context.set(state)
    try:
        with pytest.raises(Exception) as caught:
            loader.load()
        details = attachment_error(state, caught.value)
        assert details["provider"] == provider
        assert f"HTTP {status}" in details["reason"]
        assert "private-body" not in str(details)
    finally:
        attachment_context.reset(token)


@pytest.mark.parametrize("provider", ["etl4lm", "mineru", "paddle_ocr"])
def test_service_success_with_malformed_response_is_explicit(monkeypatch, tmp_path, provider):
    from bisheng.knowledge.rag.pipeline.loader import etl4lm, mineru, paddle_ocr

    file = tmp_path / "a.pdf"
    file.write_bytes(b"pdf")
    params = {
        "url": "http://unused",
        "file_path": str(file),
        "file_metadata": {},
        "file_extension": "pdf",
        "tmp_dir": str(tmp_path),
    }
    classes = {"etl4lm": etl4lm.Etl4lmLoader, "paddle_ocr": paddle_ocr.PaddleOcrLoader, "mineru": mineru.MineruLoader}
    if provider == "etl4lm":
        params["ocr_sdk_url"] = ""
    loader = classes[provider](**params)
    response = requests.Response()
    response.status_code = 200
    response._content = b"[]"
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    state = {"filename": "a.pdf", "provider": provider, "stage": "parse"}
    token = attachment_context.set(state)
    try:
        with pytest.raises(Exception) as caught:
            loader.load()
        assert attachment_error(state, caught.value)["code"] == "ATTACHMENT_PARSER_RESPONSE_INVALID"
    finally:
        attachment_context.reset(token)


def test_conversion_tool_missing_retains_real_source(monkeypatch, tmp_path):
    from bisheng.knowledge.rag.pipeline.loader.utils import libreoffice_converter

    file = tmp_path / "a.doc"
    file.write_bytes(b"doc")
    monkeypatch.setattr(libreoffice_converter, "get_libreoffice_path", lambda: None)
    state = {"filename": "a.doc", "provider": "local_word", "stage": "parse"}
    token = attachment_context.set(state)
    try:
        assert not libreoffice_converter.convert_doc_to_docx(str(file))
        details = attachment_error(state, RuntimeError("convert to docx failed"))
        assert details["source"] == "LibreOffice 格式转换"
        assert details["code"] == "ATTACHMENT_CONVERSION_TOOL_MISSING"
    finally:
        attachment_context.reset(token)


async def test_upload_error_envelope_keeps_details_and_closes_file():
    # 执行真实上传函数并隔离未涉及的路由注册和外部存储依赖。
    import ast
    from pathlib import Path

    from fastapi import Body, File, Form

    path = Path(__file__).parents[2] / "bisheng/workstation/api/endpoints/knowledge.py"
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "upload_file")
    function.decorator_list = []
    ns = {
        "File": File,
        "Form": Form,
        "Body": Body,
        "LoginUserDep": None,
        "logger": SimpleNamespace(exception=lambda *args: None),
        "save_uploaded_file": AsyncMock(side_effect=OSError("private-location")),
    }
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), ns)
    upload = SimpleNamespace(filename="a.pdf", close=AsyncMock())
    with pytest.raises(AttachmentQuestionError) as caught:
        await ns["upload_file"](None, upload, "temp-id", True, SimpleNamespace(user_id=1))
    assert caught.value.kwargs["attachment_errors"][0]["provider"] == "attachment_upload"
    assert "private-location" not in str(caught.value.kwargs)
    upload.close.assert_awaited_once()


async def test_image_without_ocr_is_reported_as_skipped(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.knowledge.domain.models.knowledge_file import ParseType
    from bisheng.workstation.domain.services.chat_service import get_file_content

    conf = SimpleNamespace(
        chunking=SimpleNamespace(max_chunk_chars=10000),
        loader_provider=ParseType.ETL4LM.value,
        etl4lm=SimpleNamespace(url=""),
    )
    monkeypatch.setattr(settings, "get_knowledge", lambda: conf)
    from bisheng.user.domain.models.user import UserDao

    monkeypatch.setattr(UserDao, "get_user", lambda _: SimpleNamespace(user_name="test"))
    state = {"filename": "image.png", "provider": "unknown", "stage": "parse"}
    token = attachment_context.set(state)
    try:
        with pytest.raises(Exception) as caught:
            await get_file_content("/image.png", "image.png", 1)
        detail = attachment_error(state, caught.value)
        assert detail["code"] == "ATTACHMENT_IMAGE_PARSER_UNAVAILABLE"
        assert detail["source"] == "本地 PDF 解析"
        assert "已跳过" in detail["reason"]
    finally:
        attachment_context.reset(token)


def test_paddle_invalid_extension_parameter_is_reported_as_request_error(monkeypatch, tmp_path):
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader

    file = tmp_path / "a.pdf"
    file.write_bytes(b"pdf")
    loader = PaddleOcrLoader(
        url="http://unused", file_path=str(file), file_metadata={}, file_extension="pdf", tmp_dir=str(tmp_path)
    )

    # 默认请求可以正常编码且只有非法扩展参数才属于请求构建错误。
    assert loader._build_payload("AA")["fileType"] == 0
    requests.Request("POST", "http://unused", json=loader._build_payload("AA")).prepare()
    loader.request_kwargs["invalid_extension"] = object()

    def prepare(url, **kwargs):
        return requests.Request("POST", url, json=kwargs["json"]).prepare()

    monkeypatch.setattr(requests, "post", prepare)
    state = {"filename": "a.pdf", "provider": "paddle_ocr", "stage": "parse"}
    token = attachment_context.set(state)
    try:
        with pytest.raises(EtlException) as caught:
            loader.load()
        error = attachment_error(state, caught.value)
        assert error["code"] == "ATTACHMENT_PARSER_REQUEST_BUILD_FAILED"
        assert error["source"] == "PaddleOCR"
    finally:
        attachment_context.reset(token)


async def test_storage_missing_object_preserves_cause_for_feedback(monkeypatch):
    from bisheng.core.cache import utils

    class MissingObject(Exception):
        code = "NoSuchKey"

    storage = SimpleNamespace(get_object=AsyncMock(side_effect=MissingObject("private-object")))
    monkeypatch.setattr(utils, "get_minio_storage", AsyncMock(return_value=storage))
    with pytest.raises(ValueError) as caught:
        await utils.async_file_download("/tmp-dir/a.pdf?X-Amz-Algorithm=mock")
    assert isinstance(caught.value.__cause__, MissingObject)
    detail = attachment_error(
        {"filename": "a.pdf", "provider": "attachment_download", "stage": "download"}, caught.value
    )
    assert detail["source"] == "附件下载"
    assert "不存在或已失效" in detail["reason"]
    assert "private-object" not in str(detail)

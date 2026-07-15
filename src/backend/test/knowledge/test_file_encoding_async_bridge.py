from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from langchain_core.documents import Document

import bisheng.knowledge.rag.pipeline.transformer.file_encoding as encoding_module
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer


def _transformer() -> FileEncodingTransformer:
    knowledge_file = SimpleNamespace(
        id=42,
        file_encoding=None,
        file_name="report.pdf",
        abstract="summary",
        knowledge_id=7,
        create_time=datetime(2026, 7, 15),
    )
    return FileEncodingTransformer(invoke_user_id=1, knowledge_file=knowledge_file)


def test_transform_documents_uses_shared_bridge_with_existing_timeout(monkeypatch) -> None:
    transformer = _transformer()
    documents = [Document(page_content="content")]
    submitted: dict[str, float] = {}

    def _run_async_safe(coro, *, timeout):
        submitted["timeout"] = timeout
        coro.close()

    monkeypatch.setattr(encoding_module, "run_async_safe", _run_async_safe)

    result = transformer.transform_documents(documents)

    assert result == documents
    assert submitted == {"timeout": 120.0}


def test_transform_documents_keeps_best_effort_behavior_on_bridge_error(monkeypatch) -> None:
    transformer = _transformer()
    documents = [Document(page_content="content")]
    warning = Mock()

    def _raise_timeout(coro, *, timeout):
        assert timeout == 120.0
        coro.close()
        raise asyncio.TimeoutError("encoding timed out")

    monkeypatch.setattr(encoding_module, "run_async_safe", _raise_timeout)
    monkeypatch.setattr(encoding_module.logger, "warning", warning)

    result = transformer.transform_documents(documents)

    assert result == documents
    warning.assert_called_once()
    assert "encoding timed out" in warning.call_args.args[0]


def test_file_encoding_module_has_no_private_event_loop_runner() -> None:
    source = inspect.getsource(encoding_module)

    assert "_AsyncRunner" not in source
    assert "new_event_loop" not in source
    assert "shougang-encoding-async" not in source

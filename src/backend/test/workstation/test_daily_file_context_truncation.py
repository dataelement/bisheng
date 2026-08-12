"""A truncated attachment must be labelled as truncated.

``_process_agent_files`` hard-cuts the extracted document text at
``ws_config.maxTokens`` CHARACTERS (the name says tokens; the slice does not) and
handed the prefix to the model with nothing marking the cut. A 1072-page tender
truncated to 15k characters therefore read as the whole document, and the model
answered questions about tables on page 400 — citing page numbers it had never
seen.

The notice does not stop truncation; it tells the model the text is partial so it
can say so instead of inventing the rest.

Everything below the cut is stubbed: no MinIO, no ETL, no model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.workstation.domain.services import chat_service


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch):
    """Feed ``_process_agent_files`` a canned document body of a chosen size."""

    def _install(doc_text: str):
        async def _fake_download(filepath):
            return "/local/tender.pdf", "tender.pdf"

        async def _fake_extract(filepath, filename, invoke_user_id):
            return doc_text

        async def _fake_covers(valid_files, downloaded_files):
            return list(valid_files)

        monkeypatch.setattr(chat_service, "async_file_download", _fake_download)
        monkeypatch.setattr(chat_service, "_extract_doc_text", _fake_extract)
        monkeypatch.setattr(chat_service, "_annotate_agent_files_with_video_covers", _fake_covers)

    return _install


def _call_args(max_tokens: int):
    data = SimpleNamespace(files=[{"file_id": "a", "filepath": "/bisheng/tender.pdf", "file_name": "tender.pdf"}])
    model_info = SimpleNamespace(visual=False)
    login_user = SimpleNamespace(user_id=1)
    ws_config = SimpleNamespace(maxTokens=max_tokens)
    return data, model_info, login_user, ws_config


async def test_truncation_is_labelled_with_both_lengths(stub_pipeline):
    stub_pipeline("x" * 40_000)

    file_context, _, _ = await chat_service._process_agent_files(*_call_args(15_000))

    assert "[TRUNCATED]" in file_context
    # The model is told what it has AND what it is missing.
    assert "15000" in file_context
    assert "40000" in file_context
    # The body itself is still cut at the configured size.
    assert file_context.startswith("x" * 15_000)


async def test_untruncated_content_is_untouched(stub_pipeline):
    stub_pipeline("short document body")

    file_context, _, _ = await chat_service._process_agent_files(*_call_args(15_000))

    assert file_context == "short document body"
    assert "TRUNCATED" not in file_context


async def test_exactly_at_the_limit_is_not_labelled(stub_pipeline):
    """Boundary: ``len == max`` loses nothing, so claiming truncation would lie."""
    stub_pipeline("y" * 100)

    file_context, _, _ = await chat_service._process_agent_files(*_call_args(100))

    assert file_context == "y" * 100
    assert "TRUNCATED" not in file_context


async def test_one_char_over_the_limit_is_labelled(stub_pipeline):
    stub_pipeline("y" * 101)

    file_context, _, _ = await chat_service._process_agent_files(*_call_args(100))

    assert "[TRUNCATED]" in file_context


async def test_notice_survives_into_the_user_content_block(stub_pipeline):
    """The notice is worthless unless it reaches the prompt the model reads."""
    stub_pipeline("z" * 40_000)

    file_context, _, _ = await chat_service._process_agent_files(*_call_args(15_000))
    content = chat_service._build_user_content(question="安装指导服务费部分有描述吗", file_context=file_context)

    assert "<uploaded_file_content>" in content
    assert "[TRUNCATED]" in content
    assert "安装指导服务费部分有描述吗" in content

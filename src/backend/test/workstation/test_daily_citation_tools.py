"""F072 — what the daily chat's retrieval tools show the model.

AC-01: knowledge chunks carry ``<ref>S3</ref>`` and web results ``"ref": "S7"``;
the registry key never appears.
AC-17: when the handle table cannot be written the results carry no source id
at all — there is no fallback to the verbatim-id contract — and the turn goes on.
"""

import json
from unittest.mock import AsyncMock

import pytest

from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope
from bisheng.workstation.domain.services import daily_citation

K1 = "knowledgesearch_aaaa1111:0"
K2 = "websearch_bbbb2222:1"


def _chunk(key: str) -> str:
    return f"{{<chunk_id>{key}</chunk_id>\n<file_title>OKR规则.docx</file_title>\n<paragraph_content>正文</paragraph_content>}}"


@pytest.fixture
def scope():
    return DailyCitationScope("chat-1")


async def test_chunks_show_handles_not_keys(monkeypatch, scope):
    monkeypatch.setattr(daily_citation, "assign_handles", AsyncMock(return_value={K1: "S3"}))

    out = await daily_citation.handles_for_chunks(scope, [object()], [_chunk(K1)])

    assert "<ref>S3</ref>" in out[0]
    assert K1 not in out[0]


async def test_chunks_carry_no_id_when_allocation_fails(monkeypatch, scope):
    monkeypatch.setattr(daily_citation, "assign_handles", AsyncMock(return_value={}))

    out = await daily_citation.handles_for_chunks(scope, [object()], [_chunk(K1)])

    assert K1 not in out[0]
    assert "<chunk_id>" not in out[0] and "<ref>" not in out[0]
    assert "正文" in out[0]


async def test_web_results_show_handles_not_keys(monkeypatch, scope):
    monkeypatch.setattr(daily_citation, "assign_handles", AsyncMock(return_value={K2: "S7"}))
    annotated = json.dumps([{"title": "OCR 2026", "url": "https://a.com", "citation_key": K2, "itemId": "1"}])

    out = json.loads(await daily_citation.handles_for_web_results(scope, [object()], annotated))

    assert out == [{"title": "OCR 2026", "url": "https://a.com", "ref": "S7"}]


async def test_web_results_carry_no_id_when_allocation_fails(monkeypatch, scope):
    monkeypatch.setattr(daily_citation, "assign_handles", AsyncMock(return_value={}))
    annotated = json.dumps([{"title": "OCR 2026", "url": "https://a.com", "citation_key": K2, "itemId": "1"}])

    out = json.loads(await daily_citation.handles_for_web_results(scope, [object()], annotated))

    assert out == [{"title": "OCR 2026", "url": "https://a.com"}]


async def test_without_a_scope_output_is_untouched():
    chunk = _chunk(K1)
    assert await daily_citation.handles_for_chunks(None, [object()], [chunk]) == [chunk]


def test_sync_path_shows_no_id(scope):
    assert "<chunk_id>" not in daily_citation.strip_ids_for_sync_path(scope, [_chunk(K1)])[0]

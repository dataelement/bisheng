"""F069 P2: export baking resolves through the permission-filtering service (AC-21 / AC-22)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
)
from bisheng.citation.domain.services import citation_export_service as svc

S, SEP, E = "", "", ""


def _rag(citation_id="knowledgesearch_aaaa1111"):
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9, documentId=11, documentName="规则.docx", items=[RagCitationItemSchema(itemId="3", page=2)]
        ),
    )


@pytest.fixture
def log_lines():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        yield lines
    finally:
        logger.remove(sink)


async def test_bake_numbers_permitted_sources_and_passes_the_exporter(monkeypatch):
    seen = {}

    async def fake_resolve(ids, login_user):
        seen["ids"] = ids
        seen["user"] = login_user
        return [_rag()]

    monkeypatch.setattr(svc, "resolve_items_for_export", fake_resolve)
    user = SimpleNamespace(user_id=7)

    out = await svc.bake_citations_for_export(f"正文。{S}knowledgesearch_aaaa1111:3{E}", user)

    assert seen["ids"] == ["knowledgesearch_aaaa1111"] and seen["user"] is user
    assert out.startswith("正文。[1]") and "## 参考资料" in out and "《规则.docx》 · 第2页" in out


async def test_bake_drops_sources_the_service_withheld(monkeypatch):
    # forbidden / expired sources simply do not come back from the resolve service
    monkeypatch.setattr(svc, "resolve_items_for_export", AsyncMock(return_value=[]))

    out = await svc.bake_citations_for_export(f"正文。{S}knowledgesearch_aaaa1111:3{E} 末尾 [S9]", SimpleNamespace(user_id=7))

    assert out == "正文。 末尾 "
    assert "参考资料" not in out


async def test_bake_without_markers_short_circuits(monkeypatch):
    resolve = AsyncMock(return_value=[_rag()])
    monkeypatch.setattr(svc, "resolve_items_for_export", resolve)

    out = await svc.bake_citations_for_export("plain text [S9]", None)

    assert out == "plain text "
    resolve.assert_not_awaited()


async def test_bake_falls_back_to_strip_on_failure(monkeypatch, log_lines):
    monkeypatch.setattr(svc, "resolve_items_for_export", AsyncMock(side_effect=RuntimeError("db down")))

    out = await svc.bake_citations_for_export(f"正文。{S}knowledgesearch_aaaa1111:3{E}", SimpleNamespace(user_id=7))

    assert out == "正文。"
    assert any("citations_baked=false" in line for line in log_lines)


async def test_resolve_items_uses_the_resolve_service_with_the_user(monkeypatch):
    captured = {}

    class _Service:
        def __init__(self, repo):
            captured["repo"] = repo

        async def resolve_citations_with_reasons(self, ids, login_user):
            captured["call"] = (ids, login_user)
            return SimpleNamespace(items=[_rag()], unresolved=[])

    class _Session:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("bisheng.citation.domain.services.citation_resolve_service.CitationResolveService", _Service)
    monkeypatch.setattr(
        "bisheng.citation.domain.repositories.implementations.message_citation_repository_impl.MessageCitationRepositoryImpl",
        lambda session: f"repo({session})",
    )
    monkeypatch.setattr("bisheng.core.database.get_async_db_session", lambda: _Session())
    user = SimpleNamespace(user_id=7)

    items = await svc.resolve_items_for_export(["knowledgesearch_aaaa1111"], user)

    assert captured["repo"] == "repo(session)"
    assert captured["call"] == (["knowledgesearch_aaaa1111"], user)
    assert items[0].citationId == "knowledgesearch_aaaa1111"


async def test_build_export_user(monkeypatch):
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))

    user = await svc.build_export_user(7, 1)
    assert user.user_id == 7 and user.tenant_id == 1 and user.is_global_super is False
    assert await svc.build_export_user(None, 1) is None

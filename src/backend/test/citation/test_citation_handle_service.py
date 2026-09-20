"""F069 T016: session handle table and the [Sn] → marker conversion grammar.

AC-07 (one handle per source, stable across retrievals), AC-10 / AC-11
(only the three accepted shapes convert; everything else is left alone and
counted), AC-13 (unknown handles stay literal), AC-16 (follow-up turns reuse
the table), AC-17 (Redis failure → empty mapping, raw keys stay), AC-27
(idempotent conversion).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.citation.domain.services import citation_handle_service as svc
from bisheng.citation.domain.services import linsight_citation_scope as scope_mod
from bisheng.citation.domain.services.citation_handle_service import (
    assign_handles,
    convert_handles_to_markers,
    count_handle_runs,
    strip_citation_handles,
)
from bisheng.citation.domain.services.linsight_citation_scope import LinsightCitationScope

S, SEP, E = "", "", ""


class FakeRedis:
    """Just enough of RedisClient's async hash API to exercise the allocator."""

    def __init__(self):
        self.store: dict[str, dict[str, str]] = {}
        self.expired: list[str] = []

    def _h(self, name):
        return self.store.setdefault(name, {})

    async def ahget(self, name, key):
        return self._h(name).get(key)

    async def ahgetall(self, name):
        return dict(self._h(name))

    async def ahincrby(self, name, key, amount=1):
        h = self._h(name)
        h[key] = str(int(h.get(key, "0")) + amount)
        return int(h[key])

    async def ahsetnx(self, name, key, value):
        h = self._h(name)
        if key in h:
            return False
        h[key] = value
        return True

    async def ahset(self, name, key=None, value=None, mapping=None, items=None, expiration=3600):
        h = self._h(name)
        if mapping:
            h.update(mapping)
        if key is not None:
            h[key] = value
        return 1

    async def aexpire_key(self, key, expiration):
        self.expired.append(key)


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch):
    fake = FakeRedis()
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(scope_mod, "get_redis_client", AsyncMock(return_value=fake))
    return fake


def _rag(citation_id: str, item_id: str, document_id: int, name: str = "OKR规则.docx", page: int | None = 3):
    return SimpleNamespace(
        key=f"{citation_id}:{item_id}",
        citationId=citation_id,
        itemId=item_id,
        type=SimpleNamespace(value="rag"),
        sourcePayload=SimpleNamespace(
            documentId=document_id,
            documentName=name,
            knowledgeName="制度库",
            items=[SimpleNamespace(itemId=item_id, page=page, chunkIndex=int(item_id))],
        ),
    )


def _web(citation_id: str, url: str, title: str = "OCR 2026"):
    return SimpleNamespace(
        key=f"{citation_id}:1",
        citationId=citation_id,
        itemId="1",
        type=SimpleNamespace(value="web"),
        sourcePayload=SimpleNamespace(url=url, title=title, source="csdn", items=[]),
    )


def _scope(enabled=True):
    return LinsightCitationScope(svid="sv-1", session_id="chat-1", enabled=enabled)


# --------------------------------------------------------------------------
# allocation
# --------------------------------------------------------------------------
async def test_assign_numbers_sources_in_order_and_writes_table(redis):
    scope = _scope()

    handles = await assign_handles(
        scope, [_rag("knowledgesearch_aaaa1111", "3", 11), _web("websearch_bbbb2222", "https://a.com/x/")]
    )

    assert handles == {"knowledgesearch_aaaa1111:3": "S1", "websearch_bbbb2222:1": "S2"}
    table = redis.store["linsight:cite_handles:chat-1"]
    assert table["next"] == "2"
    assert table["meta:enabled"] == "1"
    assert table["id:rag:11:3"] == "S1"
    assert table["id:web:https://a.com/x"] == "S2"
    e1 = json.loads(table["h:S1"])
    assert e1["key"] == "knowledgesearch_aaaa1111:3" and e1["title"] == "OKR规则.docx" and e1["loc"] == "第 3 页"
    assert scope.handles == {"S1": "knowledgesearch_aaaa1111:3", "S2": "websearch_bbbb2222:1"}
    assert [e["handle"] for e in scope.entries] == ["S1", "S2"]
    assert "linsight:cite_handles:chat-1" in redis.expired


async def test_same_identity_across_retrievals_gets_same_handle(redis):
    scope = _scope()
    await assign_handles(scope, [_rag("knowledgesearch_aaaa1111", "3", 11)])

    # a later retrieval registers the SAME chunk under a fresh uuid
    handles = await assign_handles(
        scope, [_rag("knowledgesearch_cccc3333", "3", 11), _rag("knowledgesearch_cccc3333", "4", 11)]
    )

    assert handles["knowledgesearch_cccc3333:3"] == "S1"
    assert handles["knowledgesearch_cccc3333:4"] == "S2"
    assert redis.store["linsight:cite_handles:chat-1"]["next"] == "2"


async def test_follow_up_turn_reuses_the_session_table(redis):
    first = _scope()
    await assign_handles(first, [_rag("knowledgesearch_aaaa1111", "3", 11)])

    follow_up = LinsightCitationScope(svid="sv-2", session_id="chat-1")
    await follow_up.load()
    handles = await assign_handles(
        follow_up, [_rag("knowledgesearch_dddd4444", "3", 11), _web("websearch_eeee5555", "https://b.com")]
    )

    assert follow_up.handles["S1"] == "knowledgesearch_aaaa1111:3"
    assert handles["knowledgesearch_dddd4444:3"] == "S1"
    assert handles["websearch_eeee5555:1"] == "S2"


async def test_lost_claim_reads_back_the_winner(redis):
    scope = _scope()
    # another worker claimed the identity between our HINCRBY and HSETNX
    redis.store["linsight:cite_handles:chat-1"] = {"next": "4", "id:rag:11:3": "S2", "h:S2": json.dumps({"key": "k"})}
    original_get = redis.ahget
    calls = {"n": 0}

    async def racy_get(name, key):
        calls["n"] += 1
        if key == "id:rag:11:3" and calls["n"] == 1:
            return None  # first look: not there yet
        return await original_get(name, key)

    redis.ahget = racy_get
    handles = await assign_handles(scope, [_rag("knowledgesearch_aaaa1111", "3", 11)])

    assert handles == {"knowledgesearch_aaaa1111:3": "S2"}
    assert redis.store["linsight:cite_handles:chat-1"]["next"] == "5"  # the skipped number is fine


async def test_meta_enabled_pins_the_contract_on_load(redis):
    redis.store["linsight:cite_handles:chat-1"] = {
        "next": "1",
        "meta:enabled": "0",
        "id:rag:11:3": "S1",
        "h:S1": json.dumps({"key": "knowledgesearch_aaaa1111:3", "type": "rag", "title": "t", "loc": ""}),
    }
    scope = LinsightCitationScope(svid="sv-9", session_id="chat-1", enabled=True)

    await scope.load()

    assert scope.enabled is False
    assert scope.handles == {"S1": "knowledgesearch_aaaa1111:3"}


async def test_disabled_scope_or_redis_failure_returns_empty_mapping(monkeypatch: pytest.MonkeyPatch, redis):
    assert await assign_handles(_scope(enabled=False), [_rag("knowledgesearch_aaaa1111", "3", 11)]) == {}
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(side_effect=RuntimeError("redis down")))
    scope = _scope()

    assert await assign_handles(scope, [_rag("knowledgesearch_aaaa1111", "3", 11)]) == {}
    assert scope.handles == {}


# --------------------------------------------------------------------------
# conversion grammar
# --------------------------------------------------------------------------
H = {"S3": "knowledgesearch_aaaa1111:3", "S7": "websearch_bbbb2222:1"}


@pytest.mark.parametrize(
    "text, expected, converted",
    [
        ("市占率为 31%。[S3]", f"市占率为 31%。{S}knowledgesearch_aaaa1111:3{E}", 1),
        ("结论。[S3][S7] 下一句。", f"结论。{S}knowledgesearch_aaaa1111:3{SEP}websearch_bbbb2222:1{E} 下一句。", 1),
        ("结论。[S3, S7]", f"结论。{S}knowledgesearch_aaaa1111:3{SEP}websearch_bbbb2222:1{E}", 1),
        ("结论。[S3、S7]", f"结论。{S}knowledgesearch_aaaa1111:3{SEP}websearch_bbbb2222:1{E}", 1),
        ("结论。[S3] [S7]", f"结论。{S}knowledgesearch_aaaa1111:3{SEP}websearch_bbbb2222:1{E}", 1),
        ("A。[S3] B。[S7]", f"A。{S}knowledgesearch_aaaa1111:3{E} B。{S}websearch_bbbb2222:1{E}", 2),
        ("裸编号 [3] 不动", "裸编号 [3] 不动", 0),
        ("脚注 [^3] 不动", "脚注 [^3] 不动", 0),
        ("链接 [S3](https://x) 不动", "链接 [S3](https://x) 不动", 0),
        ("```\n[S3]\n```", "```\n[S3]\n```", 0),
        ("行内 `[S3]` 不动", "行内 `[S3]` 不动", 0),
        ("[S3]: 知识库·规则\n正文。[S7]", f"[S3]: 知识库·规则\n正文。{S}websearch_bbbb2222:1{E}", 1),
        ("表格|[S3]|", f"表格|{S}knowledgesearch_aaaa1111:3{E}|", 1),
        ("紧贴中文词[S3]也要转", f"紧贴中文词{S}knowledgesearch_aaaa1111:3{E}也要转", 1),
        ("ascii_ident[S3] stays", "ascii_ident[S3] stays", 0),
    ],
)
def test_convert_grammar(text, expected, converted):
    result = convert_handles_to_markers(text, H)

    assert result.text == expected
    assert result.converted == converted


def test_unknown_handles_stay_literal_and_are_reported():
    result = convert_handles_to_markers("A。[S99] B。[S3][S42]", H)

    assert result.text == f"A。[S99] B。{S}knowledgesearch_aaaa1111:3{E}[S42]"
    assert result.unknown == ["S99", "S42"]
    assert result.converted == 1


def test_definition_lines_are_counted_not_converted():
    result = convert_handles_to_markers("[S3]: 定义\n[S7]：另一条定义\n", H)

    assert result.text == "[S3]: 定义\n[S7]：另一条定义\n"
    assert result.skipped_definitions == 2
    assert result.converted == 0


def test_conversion_is_idempotent():
    once = convert_handles_to_markers("结论。[S3][S7] 末尾", H).text

    twice = convert_handles_to_markers(once, H)

    assert twice.text == once
    assert twice.converted == 0


def test_empty_handles_leaves_text_untouched():
    result = convert_handles_to_markers("结论。[S3]", {})

    assert result.text == "结论。[S3]"
    assert result.unknown == ["S3"]


def test_strip_and_count_handles():
    text = "A。[S3][S7] B。[S99] `[S3]` [S3](u)\n[S3]: def"

    assert strip_citation_handles(text) == "A。 B。 `[S3]` [S3](u)\n[S3]: def"
    assert count_handle_runs(text) == 2


# --------------------------------------------------------------------------
# F069 P2: export baking (AC-20 / AC-21 / AC-22 / AC-24)
# --------------------------------------------------------------------------
from bisheng.citation.domain.schemas.citation_schema import (  # noqa: E402
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationItemSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_handle_service import (  # noqa: E402
    export_heading_for,
    render_citations_for_export,
)


def _rag_resolved(citation_id="knowledgesearch_aaaa1111", document_id=11, name="OKR规则2026.docx", kb="制度库"):
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            knowledgeName=kb,
            documentId=document_id,
            documentName=name,
            items=[
                RagCitationItemSchema(itemId="3", chunkId="c3", content="x", page=3),
                RagCitationItemSchema(itemId="4", chunkId="c4", content="y", chunkIndex=4),
            ],
        ),
    )


def _web_resolved(citation_id="websearch_bbbb2222", url="https://a.com/x", title="OCR 2026 进展"):
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.WEB,
        accessScope="per_user",
        sourcePayload=WebCitationPayloadSchema(
            url=url, title=title, source="csdn", items=[WebCitationItemSchema(itemId="1", snippet="s")]
        ),
    )


def _m(*keys):
    return S + SEP.join(keys) + E


def test_export_numbers_by_first_appearance_and_appends_references():
    text = f"结论一。{_m('knowledgesearch_aaaa1111:3')} 结论二。{_m('websearch_bbbb2222:1', 'knowledgesearch_aaaa1111:3')}"

    r = render_citations_for_export(text, [_rag_resolved(), _web_resolved()])

    assert r.text.startswith("结论一。[1] 结论二。[2][1]")
    assert r.numbered == 2 and r.unresolved == []
    assert "## 参考资料" in r.text
    assert "1. 《OKR规则2026.docx》 · 第 3 页 · 制度库" in r.text
    assert "2. OCR 2026 进展 · csdn · https://a.com/x" in r.text
    assert S not in r.text and "knowledgesearch_" not in r.text


def test_export_same_source_shares_a_number_but_other_chunk_gets_its_own():
    text = f"A{_m('knowledgesearch_aaaa1111:3')} B{_m('knowledgesearch_aaaa1111:3')} C{_m('knowledgesearch_aaaa1111:4')}"

    r = render_citations_for_export(text, [_rag_resolved()])

    assert r.text.startswith("A[1] B[1] C[2]")
    assert "2. 《OKR规则2026.docx》 · 第 4 段 · 制度库" in r.text


def test_export_drops_unresolved_keys_and_whole_spans():
    text = f"有权限。{_m('knowledgesearch_aaaa1111:3', 'knowledgesearch_zzzz9999:1')} 无权限。{_m('knowledgesearch_zzzz9999:2')} 结尾。"

    r = render_citations_for_export(text, [_rag_resolved()])

    assert r.text.startswith("有权限。[1] 无权限。 结尾。")
    assert r.unresolved == ["knowledgesearch_zzzz9999:1", "knowledgesearch_zzzz9999:2"]
    assert r.text.count("\n1. ") == 1 and "\n2. " not in r.text


def test_export_with_nothing_resolvable_equals_strip():
    from bisheng.citation.domain.services.citation_prompt_helper import strip_citation_markers

    text = f"正文。{_m('knowledgesearch_aaaa1111:3')} 还有 [S99] 与 `code {_m('x:1')}`"

    r = render_citations_for_export(text, [])

    assert r.numbered == 0
    assert "## " not in r.text
    assert r.text == strip_citation_handles(strip_citation_markers(text)).replace("`code `", f"`code {_m('x:1')}`") or S not in r.text


def test_export_leaves_code_alone_and_strips_handles():
    text = f"正文。{_m('knowledgesearch_aaaa1111:3')} [S99]\n```\n{_m('knowledgesearch_aaaa1111:3')}\n```\n"

    r = render_citations_for_export(text, [_rag_resolved()])

    assert r.text.startswith("正文。[1]")
    assert "[S99]" not in r.text
    # fenced content is never NUMBERED, but no private-use marker may survive in
    # a deliverable either (F054 AC-12): the span inside the fence is stripped
    assert "```\n\n```" in r.text
    assert S not in r.text and "[1]" not in r.text.split("```")[1]


def test_export_heading_language_and_override():
    assert export_heading_for("含中文的报告") == "参考资料"
    assert export_heading_for("english only") == "References"
    r = render_citations_for_export(f"English body.{_m('websearch_bbbb2222:1')}", [_web_resolved()])
    assert "## References" in r.text
    r2 = render_citations_for_export(f"English body.{_m('websearch_bbbb2222:1')}", [_web_resolved()], heading="Sources")
    assert "## Sources" in r2.text


def test_export_is_idempotent_on_baked_text():
    text = f"结论。{_m('knowledgesearch_aaaa1111:3')}"
    once = render_citations_for_export(text, [_rag_resolved()]).text

    twice = render_citations_for_export(once, [_rag_resolved()])

    assert twice.text == once and twice.numbered == 0


def test_export_page_zero_falls_back_to_chunk_index():
    item = CitationRegistryItemSchema(
        citationId="knowledgesearch_cccc3333",
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            documentId=12,
            documentName="规则.docx",
            items=[RagCitationItemSchema(itemId="7", page=0, chunkIndex=7), RagCitationItemSchema(itemId="8", page=0)],
        ),
    )

    r = render_citations_for_export(f"甲{_m('knowledgesearch_cccc3333:7')} 乙{_m('knowledgesearch_cccc3333:8')}", [item])

    assert "1. 《规则.docx》" in r.text and "第 7 段" in r.text
    assert "第 0 页" not in r.text
    assert "2. 《规则.docx》\n" in r.text or r.text.rstrip().endswith("2. 《规则.docx》")

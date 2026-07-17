"""历史知识库文件二级分类补全脚本测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import text
from sqlmodel import select

import scripts.backfill_file_subcategories as script_mod
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import (
    FileEncodingTransformer,
    FileSubcategoryOption,
)


@pytest.fixture()
async def subcategory_db(async_db_session):
    """测试基础 DDL 尚未包含后续迁移列, 在用例引擎中局部补齐。"""
    await async_db_session.exec(text("ALTER TABLE knowledge ADD COLUMN sort_weight INTEGER"))
    await async_db_session.exec(text("ALTER TABLE knowledgefile ADD COLUMN file_subcategory_code VARCHAR(16)"))
    await async_db_session.exec(text("ALTER TABLE knowledgefile ADD COLUMN file_subcategory_source VARCHAR(16)"))
    await async_db_session.commit()
    return async_db_session


async def _seed_space(
    session,
    *,
    knowledge_id: int,
    tenant_id: int = 1,
    knowledge_type: int = KnowledgeTypeEnum.SPACE.value,
    index_name: str | None = "knowledge-index",
) -> None:
    with bypass_tenant_filter():
        session.add(
            Knowledge(
                id=knowledge_id,
                tenant_id=tenant_id,
                name=f"space-{knowledge_id}",
                type=knowledge_type,
                user_id=1,
                index_name=index_name,
            )
        )
        await session.commit()


async def _seed_file(
    session,
    *,
    file_id: int,
    knowledge_id: int,
    tenant_id: int = 1,
    status: int = KnowledgeFileStatus.SUCCESS.value,
    file_type: int = FileType.FILE.value,
    subcategory_code: str | None = None,
    file_encoding: str | None = "SGGF-STD-IT-20260700000001",
) -> None:
    with bypass_tenant_filter():
        session.add(
            KnowledgeFile(
                id=file_id,
                tenant_id=tenant_id,
                knowledge_id=knowledge_id,
                file_name=f"file-{file_id}.pdf",
                abstract=f"abstract-{file_id}",
                file_type=file_type,
                status=status,
                file_encoding=file_encoding,
                file_subcategory_code=subcategory_code,
            )
        )
        await session.commit()


def _file(*, file_id: int = 1, tenant_id: int = 1, file_encoding: str | None = None):
    return SimpleNamespace(
        id=file_id,
        tenant_id=tenant_id,
        knowledge_id=10,
        file_name="安全操作规程.pdf",
        abstract="涵盖炼钢安全操作要求",
        file_encoding=file_encoding or "SGGF-STD-SA-20260700000001",
        file_subcategory_code=None,
        file_subcategory_source=None,
    )


def _options() -> tuple[FileSubcategoryOption, ...]:
    return (
        FileSubcategoryOption(code="STD_SAFE", label="安全规程", parent_code="STD", parent_label="标准规范"),
        FileSubcategoryOption(code="STD_TECH", label="技术标准", parent_code="STD", parent_label="标准规范"),
    )


@pytest.mark.asyncio
async def test_dry_run_filters_candidates_pages_and_has_no_external_side_effects(
    subcategory_db,
    monkeypatch,
):
    await _seed_space(subcategory_db, knowledge_id=10, tenant_id=1)
    await _seed_space(subcategory_db, knowledge_id=20, tenant_id=2)
    await _seed_space(
        subcategory_db,
        knowledge_id=30,
        tenant_id=3,
        knowledge_type=KnowledgeTypeEnum.NORMAL.value,
    )
    await _seed_file(subcategory_db, file_id=101, knowledge_id=10, tenant_id=1)
    await _seed_file(subcategory_db, file_id=102, knowledge_id=20, tenant_id=2, subcategory_code="   ")
    await _seed_file(
        subcategory_db,
        file_id=103,
        knowledge_id=10,
        tenant_id=1,
        status=KnowledgeFileStatus.FAILED.value,
    )
    await _seed_file(
        subcategory_db,
        file_id=104,
        knowledge_id=10,
        tenant_id=1,
        file_type=FileType.DIR.value,
    )
    await _seed_file(subcategory_db, file_id=105, knowledge_id=10, tenant_id=1, subcategory_code="STD_SAFE")
    await _seed_file(subcategory_db, file_id=106, knowledge_id=30, tenant_id=3)
    processor = AsyncMock()
    monkeypatch.setattr(script_mod, "process_file", processor)

    report = await script_mod.backfill(subcategory_db, apply=False, batch_size=1)

    assert report.total_scanned == 2
    assert report.eligible == 2
    assert report.would_process == 2
    assert report.fallback_saved == 0
    assert report.ai_saved == 0
    processor.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_respects_scope_filters_and_limit(subcategory_db):
    await _seed_space(subcategory_db, knowledge_id=10, tenant_id=1)
    await _seed_space(subcategory_db, knowledge_id=20, tenant_id=2)
    await _seed_file(subcategory_db, file_id=101, knowledge_id=10, tenant_id=1)
    await _seed_file(subcategory_db, file_id=102, knowledge_id=10, tenant_id=1)
    await _seed_file(subcategory_db, file_id=201, knowledge_id=20, tenant_id=2)

    tenant_report = await script_mod.backfill(subcategory_db, apply=False, tenant_id=1, limit=1, batch_size=1)
    file_report = await script_mod.backfill(subcategory_db, apply=False, file_id=201)

    assert tenant_report.total_scanned == 1
    assert tenant_report.would_process == 1
    assert file_report.total_scanned == 1
    assert file_report.would_process == 1


def test_extract_document_type_rejects_missing_or_invalid_encoding():
    assert script_mod._extract_document_type_code("SGGF-STD-SA-20260700000001") == "STD"
    assert script_mod._extract_document_type_code(None) is None
    assert script_mod._extract_document_type_code("BAD") is None


@pytest.mark.asyncio
async def test_load_options_uses_current_tenant_portal_children(monkeypatch):
    document_types = [
        {
            "code": "STD",
            "label": "标准规范",
            "children": [
                {"code": "STD_SAFE", "label": "安全规程"},
                {"code": "STD_TECH", "label": "技术标准"},
            ],
        }
    ]
    config = SimpleNamespace(portal=SimpleNamespace(document_types=document_types))
    get_config = AsyncMock(return_value=config)
    monkeypatch.setattr(script_mod.ShougangPortalConfigService, "get_config", get_config)
    knowledge_file = _file(tenant_id=7)
    transformer = FileEncodingTransformer(invoke_user_id=0, knowledge_file=knowledge_file)

    resolution = await script_mod._load_subcategory_options(knowledge_file, transformer)

    assert [option.code for option in resolution.options] == ["STD_SAFE", "STD_TECH"]
    assert resolution.reason is None
    get_config.assert_awaited_once_with(tenant_id=7)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "encoding", "reason"),
    [
        (None, "SGGF-STD-SA-20260700000001", "portal_config_unavailable"),
        (
            SimpleNamespace(
                portal=SimpleNamespace(
                    document_types=[{"code": "RPT", "label": "报告", "children": [{"code": "RPT_A"}]}]
                )
            ),
            "SGGF-STD-SA-20260700000001",
            "parent_not_configured",
        ),
        (
            SimpleNamespace(portal=SimpleNamespace(document_types=[{"code": "STD", "label": "标准", "children": []}])),
            "SGGF-STD-SA-20260700000001",
            "no_valid_candidates",
        ),
        (
            SimpleNamespace(
                portal=SimpleNamespace(document_types=[{"code": "STD", "label": "标准", "children": [{"code": "***"}]}])
            ),
            "SGGF-STD-SA-20260700000001",
            "no_valid_candidates",
        ),
        (SimpleNamespace(portal=SimpleNamespace(document_types=[])), "BAD", "invalid_file_encoding"),
    ],
)
async def test_load_options_returns_stable_skip_reasons(monkeypatch, config, encoding, reason):
    monkeypatch.setattr(script_mod.ShougangPortalConfigService, "get_config", AsyncMock(return_value=config))
    knowledge_file = _file(file_encoding=encoding)
    transformer = FileEncodingTransformer(invoke_user_id=0, knowledge_file=knowledge_file)

    resolution = await script_mod._load_subcategory_options(knowledge_file, transformer)

    assert resolution.options == ()
    assert resolution.reason == reason


def test_read_content_head_sorts_normalizes_and_truncates(monkeypatch):
    long_text = "B" * 1600
    client = SimpleNamespace(
        search=Mock(
            return_value={
                "_scroll_id": "scroll-1",
                "hits": {
                    "hits": [
                        {"_id": "b", "_source": {"text": long_text, "metadata": {"chunk_index": 2}}},
                        {"_id": "a", "_source": {"text": "  A\n\tA  ", "metadata": {"chunk_index": 1}}},
                    ]
                },
            }
        ),
        scroll=Mock(return_value={"_scroll_id": "scroll-1", "hits": {"hits": []}}),
        clear_scroll=Mock(),
    )
    monkeypatch.setattr(
        script_mod.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        Mock(return_value=SimpleNamespace(client=client)),
    )
    knowledge = SimpleNamespace(id=10, index_name="knowledge-index")

    result = script_mod._read_content_head_sync(knowledge, file_id=1)

    assert result.reason is None
    assert result.content.startswith("A A ")
    assert len(result.content) == 1500
    client.clear_scroll.assert_called_once_with(scroll_id="scroll-1")


@pytest.mark.parametrize(
    ("index_name", "search_result", "search_error", "reason"),
    [
        (None, None, None, "knowledge_index_missing"),
        ("idx", {"hits": {"hits": []}}, None, "es_content_empty"),
        ("idx", None, RuntimeError("ES unavailable"), "es_read_failed"),
    ],
)
def test_read_content_head_returns_stable_failure_reasons(
    monkeypatch,
    index_name,
    search_result,
    search_error,
    reason,
):
    client = SimpleNamespace(search=Mock(), clear_scroll=Mock())
    if search_error:
        client.search.side_effect = search_error
    else:
        client.search.return_value = search_result
    monkeypatch.setattr(
        script_mod.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        Mock(return_value=SimpleNamespace(client=client)),
    )

    result = script_mod._read_content_head_sync(SimpleNamespace(id=10, index_name=index_name), file_id=1)

    assert result.content == ""
    assert result.reason == reason


@pytest.mark.asyncio
async def test_select_with_ai_retries_invalid_and_exception_then_succeeds(monkeypatch):
    knowledge_file = _file(tenant_id=8)
    transformer = FileEncodingTransformer(invoke_user_id=0, knowledge_file=knowledge_file)
    transformer.content_head = "转炉区域作业前必须进行安全确认"
    fake_llm = SimpleNamespace(
        ainvoke=AsyncMock(
            side_effect=[
                SimpleNamespace(content="OUTSIDE"),
                RuntimeError("temporary failure"),
                SimpleNamespace(content="std_safe"),
            ]
        )
    )
    monkeypatch.setattr(
        script_mod.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(chat_title_llm=SimpleNamespace(id=123))),
    )
    create_llm = AsyncMock(return_value=fake_llm)
    monkeypatch.setattr(script_mod.LLMService, "get_bisheng_llm", create_llm)

    selection = await script_mod._select_with_ai(transformer, _options())

    assert selection.option == _options()[0]
    assert selection.attempts == 3
    assert selection.reason is None
    assert fake_llm.ainvoke.await_count == 3
    assert create_llm.await_args_list[0].kwargs["temperature"] == 0
    prompt = fake_llm.ainvoke.await_args_list[0].args[0][1]["content"]
    assert "安全操作规程.pdf" in prompt
    assert "炼钢安全操作要求" in prompt
    assert "转炉区域" in prompt
    assert "STD_SAFE" in prompt


@pytest.mark.asyncio
async def test_select_with_ai_exhausts_three_attempts_without_fallback(monkeypatch):
    transformer = FileEncodingTransformer(invoke_user_id=0, knowledge_file=_file())
    fake_llm = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="INVALID")))
    monkeypatch.setattr(
        script_mod.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(chat_title_llm=SimpleNamespace(id=123))),
    )
    monkeypatch.setattr(script_mod.LLMService, "get_bisheng_llm", AsyncMock(return_value=fake_llm))

    selection = await script_mod._select_with_ai(transformer, _options())

    assert selection.option is None
    assert selection.attempts == 3
    assert selection.reason == "ai_attempts_exhausted"
    assert fake_llm.ainvoke.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("success_attempt", [1, 2])
async def test_select_with_ai_stops_after_first_valid_response(monkeypatch, success_attempt):
    transformer = FileEncodingTransformer(invoke_user_id=0, knowledge_file=_file())
    responses = [SimpleNamespace(content="INVALID")] * (success_attempt - 1)
    responses.append(SimpleNamespace(content="STD_TECH"))
    fake_llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
    monkeypatch.setattr(
        script_mod.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(chat_title_llm=SimpleNamespace(id=123))),
    )
    monkeypatch.setattr(script_mod.LLMService, "get_bisheng_llm", AsyncMock(return_value=fake_llm))

    selection = await script_mod._select_with_ai(transformer, _options())

    assert selection.option == _options()[1]
    assert selection.attempts == success_attempt
    assert fake_llm.ainvoke.await_count == success_attempt


@pytest.mark.asyncio
async def test_select_with_ai_skips_when_model_config_is_missing(monkeypatch):
    transformer = FileEncodingTransformer(invoke_user_id=0, knowledge_file=_file())
    monkeypatch.setattr(
        script_mod.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(chat_title_llm=None)),
    )
    create_llm = AsyncMock()
    monkeypatch.setattr(script_mod.LLMService, "get_bisheng_llm", create_llm)

    selection = await script_mod._select_with_ai(transformer, _options())

    assert selection.option is None
    assert selection.attempts == 0
    assert selection.reason == "llm_config_missing"
    create_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_file_single_candidate_skips_es_and_ai(monkeypatch):
    option = _options()[0]
    monkeypatch.setattr(
        script_mod,
        "_load_subcategory_options",
        AsyncMock(return_value=script_mod.OptionsResolution(options=(option,))),
    )
    read_content = AsyncMock()
    select_ai = AsyncMock()
    writer = AsyncMock(return_value=True)
    monkeypatch.setattr(script_mod, "_read_content_head", read_content)
    monkeypatch.setattr(script_mod, "_select_with_ai", select_ai)
    monkeypatch.setattr(script_mod, "_conditional_write", writer)

    result = await script_mod.process_file(
        SimpleNamespace(),
        _file(),
        SimpleNamespace(id=10, index_name=None),
    )

    assert result.status == "saved"
    assert result.source == "fallback"
    read_content.assert_not_awaited()
    select_ai.assert_not_awaited()
    writer.assert_awaited_once_with(SimpleNamespace(), file_id=1, code="STD_SAFE", source="fallback")


@pytest.mark.asyncio
async def test_process_file_multi_candidate_requires_es_and_ai(monkeypatch):
    options = _options()
    monkeypatch.setattr(
        script_mod,
        "_load_subcategory_options",
        AsyncMock(return_value=script_mod.OptionsResolution(options=options)),
    )
    monkeypatch.setattr(
        script_mod,
        "_read_content_head",
        AsyncMock(return_value=script_mod.ContentHeadResult(content="正文开头")),
    )
    monkeypatch.setattr(
        script_mod,
        "_select_with_ai",
        AsyncMock(return_value=script_mod.AISelection(option=options[1], attempts=2)),
    )
    writer = AsyncMock(return_value=True)
    monkeypatch.setattr(script_mod, "_conditional_write", writer)

    result = await script_mod.process_file(
        SimpleNamespace(),
        _file(),
        SimpleNamespace(id=10, index_name="idx"),
    )

    assert result.status == "saved"
    assert result.source == "ai"
    assert result.attempts == 2
    writer.assert_awaited_once_with(SimpleNamespace(), file_id=1, code="STD_TECH", source="ai")


@pytest.mark.asyncio
async def test_process_file_does_not_call_ai_when_es_is_empty(monkeypatch):
    monkeypatch.setattr(
        script_mod,
        "_load_subcategory_options",
        AsyncMock(return_value=script_mod.OptionsResolution(options=_options())),
    )
    monkeypatch.setattr(
        script_mod,
        "_read_content_head",
        AsyncMock(return_value=script_mod.ContentHeadResult(reason="es_content_empty")),
    )
    select_ai = AsyncMock()
    writer = AsyncMock()
    monkeypatch.setattr(script_mod, "_select_with_ai", select_ai)
    monkeypatch.setattr(script_mod, "_conditional_write", writer)

    result = await script_mod.process_file(
        SimpleNamespace(),
        _file(),
        SimpleNamespace(id=10, index_name="idx"),
    )

    assert result.status == "skipped"
    assert result.reason == "es_content_empty"
    select_ai.assert_not_awaited()
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_file_does_not_write_when_ai_attempts_are_exhausted(monkeypatch):
    monkeypatch.setattr(
        script_mod,
        "_load_subcategory_options",
        AsyncMock(return_value=script_mod.OptionsResolution(options=_options())),
    )
    monkeypatch.setattr(
        script_mod,
        "_read_content_head",
        AsyncMock(return_value=script_mod.ContentHeadResult(content="正文开头")),
    )
    monkeypatch.setattr(
        script_mod,
        "_select_with_ai",
        AsyncMock(
            return_value=script_mod.AISelection(
                attempts=3,
                reason="ai_attempts_exhausted",
            )
        ),
    )
    writer = AsyncMock()
    monkeypatch.setattr(script_mod, "_conditional_write", writer)

    result = await script_mod.process_file(
        SimpleNamespace(),
        _file(),
        SimpleNamespace(id=10, index_name="idx"),
    )

    assert result.status == "skipped"
    assert result.reason == "ai_attempts_exhausted"
    assert result.attempts == 3
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_conditional_write_is_atomic_and_does_not_overwrite(subcategory_db):
    await _seed_space(subcategory_db, knowledge_id=10, tenant_id=1)
    await _seed_file(subcategory_db, file_id=101, knowledge_id=10, tenant_id=1)
    token = set_current_tenant_id(1)
    try:
        first = await script_mod._conditional_write(
            subcategory_db,
            file_id=101,
            code="STD_SAFE",
            source="ai",
        )
        second = await script_mod._conditional_write(
            subcategory_db,
            file_id=101,
            code="STD_TECH",
            source="fallback",
        )
    finally:
        current_tenant_id.reset(token)

    with bypass_tenant_filter():
        stored = (await subcategory_db.exec(select(KnowledgeFile).where(KnowledgeFile.id == 101))).one()
    assert first is True
    assert second is False
    assert stored.file_subcategory_code == "STD_SAFE"
    assert stored.file_subcategory_source == "ai"


@pytest.mark.asyncio
async def test_conditional_write_cannot_cross_tenant_boundary(subcategory_db):
    await _seed_space(subcategory_db, knowledge_id=20, tenant_id=2)
    await _seed_file(subcategory_db, file_id=201, knowledge_id=20, tenant_id=2)
    token = set_current_tenant_id(1)
    try:
        saved = await script_mod._conditional_write(
            subcategory_db,
            file_id=201,
            code="STD_SAFE",
            source="ai",
        )
    finally:
        current_tenant_id.reset(token)

    with bypass_tenant_filter():
        stored = (await subcategory_db.exec(select(KnowledgeFile).where(KnowledgeFile.id == 201))).one()
    assert saved is False
    assert stored.file_subcategory_code is None


@pytest.mark.asyncio
async def test_backfill_continues_after_file_error_and_resets_tenant_context(
    subcategory_db,
    monkeypatch,
):
    await _seed_space(subcategory_db, knowledge_id=10, tenant_id=1)
    await _seed_space(subcategory_db, knowledge_id=20, tenant_id=2)
    await _seed_file(subcategory_db, file_id=101, knowledge_id=10, tenant_id=1)
    await _seed_file(subcategory_db, file_id=201, knowledge_id=20, tenant_id=2)
    seen_tenants: list[int | None] = []

    async def processor(_session, _knowledge_file, _knowledge):
        seen_tenants.append(get_current_tenant_id())
        if len(seen_tenants) == 1:
            raise RuntimeError("secret document body must not leak")
        return script_mod.ProcessResult(status="saved", source="fallback")

    monkeypatch.setattr(script_mod, "process_file", processor)
    original_token = set_current_tenant_id(99)
    try:
        report = await script_mod.backfill(subcategory_db, apply=True, batch_size=2)
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(original_token)

    assert seen_tenants == [1, 2]
    assert report.fallback_saved == 1
    assert report.unexpected_errors == 1
    assert report.details[0].file_id == 101
    assert report.details[0].error_type == "RuntimeError"
    assert "secret" not in str(report.details[0])

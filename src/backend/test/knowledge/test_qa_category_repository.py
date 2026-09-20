from datetime import datetime

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)


async def test_category_candidates_execute_filtered_cursor_query(async_db_session):
    def file(file_id, **extra):
        values = {
            "id": file_id,
            "tenant_id": 1,
            "knowledge_id": 10,
            "file_name": f"{file_id}.pdf",
            "file_encoding": "SG-ZC-A-001",
            "file_subcategory_code": "A",
            "status": 2,
            "file_type": 1,
        }
        values.update(extra)
        return KnowledgeFile(**values)

    async_db_session.add_all(
        [
            file(100),
            file(99),
            file(98),
            file(97),
            file(105, knowledge_id=11),
            file(104, status=3),
            file(103, file_type=0),
            file(102, file_subcategory_code="B"),
            file(101, deleted_at=datetime(2026, 9, 10)),
            file(106, file_encoding="SG-BG-A-001"),
            file(96, file_encoding=" SG - zc - A - 001 ", file_subcategory_code=" a "),
        ]
    )
    await async_db_session.commit()
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    first = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=None, limit=2
    )
    second = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=first[-1].id, limit=2
    )
    assert [f.id for f in first] == [100, 99]
    assert [f.id for f in second] == [98, 97]
    third = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=97, limit=2,
    )
    assert [f.id for f in third] == [96]
    assert (
        await repository.list_qa_category_candidates(
            space_ids=[], document_type=None, file_subcategory_code=None, before_id=None, limit=2
        )
        == []
    )

    # 统计读取完整匹配集合，不被列表分页的 limit 截断。
    stats = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=None, limit=None,
    )
    assert {f.id for f in stats} == {100, 99, 98, 97, 96}


async def test_category_metadata_and_candidates_enforce_real_tenant_filter(
    async_db_session, monkeypatch,
):
    from contextlib import asynccontextmanager
    from sqlalchemy import event, text
    from bisheng.core.database import tenant_filter
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.services import knowledge_space_service as module

    for sid, tenant, kind, state in [(10, 1, 3, 1), (20, 2, 3, 1), (30, 1, 3, 5), (40, 1, 0, 1), (50, 1, 3, 1)]:
        async_db_session.add(Knowledge(id=sid, name=str(sid), tenant_id=tenant, type=kind, state=state))
        async_db_session.add(KnowledgeFile(id=sid, knowledge_id=sid, tenant_id=tenant,
                                          file_name='test.pdf', file_encoding='SG-ZC-A-001',
                                          file_subcategory_code='A', file_type=1, status=2))
        if sid != 50:
            await async_db_session.execute(text(
                "INSERT INTO knowledge_space_scope (space_id, tenant_id, level, owner_type, owner_id, created_by) "
                "VALUES (:sid, :tenant, 'public', 'user', 1, 1)"), {'sid': sid, 'tenant': tenant})
    await async_db_session.commit()
    token = set_current_tenant_id(1)
    handlers = []
    listen = event.listens_for

    def capture(target, name, **kwargs):
        def register(fn):
            handlers.append((target, name, fn))
            return listen(target, name, **kwargs)(fn)
        return register

    monkeypatch.setattr(tenant_filter, '_initialized', False)
    monkeypatch.setattr(tenant_filter, '_tenant_aware_tables', set())
    monkeypatch.setattr(tenant_filter, '_force_import_all_models', lambda: None)
    monkeypatch.setattr(event, 'listens_for', capture)
    tenant_filter.register_tenant_filter_events()

    @asynccontextmanager
    async def session():
        yield async_db_session

    monkeypatch.setattr(module, 'get_async_db_session', session)
    service = object.__new__(module.KnowledgeSpaceService)
    try:
        rows = await service._load_qa_category_space_metadata([10, 20, 30, 40, 50])
        assert {(space.id, level) for space, level in rows} == {(10, 'public'), (50, None)}
        candidates = await KnowledgeFileRepositoryImpl(async_db_session).list_qa_category_candidates(
            space_ids=[10, 20, 30, 40, 50], document_type='ZC', file_subcategory_code='A',
            before_id=None, limit=None)
        assert {f.knowledge_id for f in candidates} == {10, 30, 40, 50}
    finally:
        for target, name, fn in handlers:
            event.remove(target, name, fn)
        current_tenant_id.reset(token)

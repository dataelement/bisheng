"""§129 actual scalar read stream, history coverage and deep-page equivalence."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import move_processing_access as module
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from test.knowledge_unification import test_move_processing_admission as stages
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


async def test_real_401_item_deep_page_has_one_scalar_scan_and_no_plan_or_manifest(application, monkeypatch):
    app = application
    await stages.reset_to_before(app)
    async with app.built.sessions() as session, session.begin():
        await session.execute(
            sa.insert(base.File.__table__),
            [
                {
                    "id": 1000 + n,
                    "tenant_id": 101,
                    "knowledge_id": 10,
                    "user_id": 7,
                    "file_name": f"{n}.txt",
                    "file_type": 1,
                    "file_level_path": "/50",
                    "level": 1,
                    "status": 2,
                }
                for n in range(400)
            ],
        )
        await session.execute(
            sa.insert(Version.__table__),
            [
                {
                    "id": 20000 + n,
                    "document_id": 80,
                    "knowledge_file_id": 1000 + n,
                    "version_no": n + 3,
                    "is_primary": False,
                }
                for n in range(400)
            ],
        )
    with request_context(app.actor):
        plan = await app.owner.aprecheck(
            10,
            FileMoveReq(items=[{"id": 50, "type": "folder"}], target_space_id=11, target_folder_id=51),
            identity=app.current,
            entry_kind="web",
        )
        accepted = await app.owner.aaccept(
            10,
            ProcessingCreateRequest(
                confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="query-stream"
            ),
            identity=app.current,
            entry_kind="web",
        )
    api = module.MoveProcessingAccess(app.owner)

    async def no_scope(*args, **kwargs):
        raise AssertionError("query must not restore full Scope")

    async def visible(identity, **kwargs):
        assert len(kwargs["resource_ids"]) <= 200
        return {str(value): ("visible",) for value in kwargs["resource_ids"]}

    monkeypatch.setattr(app.owner, "_scope_for", no_scope)
    monkeypatch.setattr(module, "batch_check_business_actions", visible)
    sql, rows = [], []
    original = api.rows.alist_items

    async def scan(*args, **kwargs):
        result = await original(*args, **kwargs)
        rows.append(len(result))
        return result

    monkeypatch.setattr(api.rows, "alist_items", scan)

    def capture(connection, cursor, statement, params, context, many):
        sql.append(statement)

    async with app.built.sessions() as session:
        engine = session.bind.sync_engine
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        with request_context(app.actor):
            for page in (1, 21):
                sql.clear()
                rows.clear()
                result = await api.alist_items(10, accepted.job_id, identity=app.current, page=page, page_size=20)
                assert result.total == 401 and rows == [200, 200, 1]
                assert len(result.data) == (20 if page == 1 else 1)
                assert not any(
                    "scope_manifest" in query
                    or "knowledge_operation_plan.parameters" in query
                    or "processing_snapshot" in query
                    for query in sql
                )
                print(
                    {
                        "page": page,
                        "native_scalar_pages": len(rows),
                        "sql": len(sql),
                        "rows_scanned": sum(rows),
                        "retained": len(result.data),
                    }
                )

            async def deny(*args, **kwargs):
                raise PermissionDeniedError()

            monkeypatch.setattr(admission, "require_business_action", deny)
            sql.clear()
            with pytest.raises(PermissionDeniedError):
                await api.aget(10, accepted.job_id, identity=app.current)
            assert not any("scope_manifest" in query or "knowledge_operation_plan.parameters" in query for query in sql)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)


async def test_off_page_candidates_do_not_expand_scope_or_read_all_item_payloads(application, monkeypatch):
    app = application
    await stages.reset_to_before(app)
    with request_context(app.actor):
        for n in range(3):
            plan = await app.owner.aprecheck(
                10,
                FileMoveReq(items=[{"id": 81, "type": "file"}], target_space_id=11),
                identity=app.current,
                entry_kind="web",
            )
            await app.owner.aaccept(
                10,
                ProcessingCreateRequest(
                    confirmation_id=plan.confirmation_id,
                    plan_digest=plan.plan_digest,
                    idempotency_key=f"actual-list-{n}",
                ),
                identity=app.current,
                entry_kind="web",
            )
    access = module.MoveProcessingAccess(app.owner)
    reads = []
    read = access._read

    async def selected_only(job, *args):
        reads.append(job.id)
        return await read(job, *args)

    async def no_scope(*args, **kwargs):
        raise AssertionError("off-page candidates must not restore Scope")

    async def visible(identity, **kwargs):
        return {str(value): ("visible",) for value in kwargs["resource_ids"]}

    monkeypatch.setattr(access, "_read", selected_only)
    monkeypatch.setattr(app.owner, "_scope_for", no_scope)
    monkeypatch.setattr(module, "batch_check_business_actions", visible)
    with request_context(app.actor):
        result = await access.alist(10, identity=app.current, page=3, page_size=1)
    assert result.total == 3 and len(result.data) == 1
    assert reads == [result.data[0].id]

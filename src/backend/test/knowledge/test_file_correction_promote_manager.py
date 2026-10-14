"""采纳更新提升后对齐 F059 manager, 并删掉 add_file 留下的空文档."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.services.knowledge_file_correction_update import (
    parent_id_from_file_level_path,
)
from test.knowledge.test_file_correction_flow import (
    _app,
    _body,
    _cleanup,
    _insert_file,
    _insert_space,
    _insert_user,
    _submit,
    _user,
    flow_env,
)


def test_parent_id_from_file_level_path():
    """根目录没有父目录, /12/34 取最后一段."""
    assert parent_id_from_file_level_path(None) is None
    assert parent_id_from_file_level_path("") is None
    assert parent_id_from_file_level_path("/") is None
    assert parent_id_from_file_level_path("/12/34") == 34
    assert parent_id_from_file_level_path("12/34") == 34
    assert parent_id_from_file_level_path("not-a-number") is None


async def _last_id(session: AsyncSession, sql: str, params: dict) -> int:
    result = await session.execute(text(sql), params)
    inserted = int(result.lastrowid or 0)
    if inserted > 0:
        return inserted
    return int((await session.execute(text("SELECT LAST_INSERT_ID()"))).scalar_one())


async def _seed_manager_document(session: AsyncSession, *, space_id: int, file_id: int) -> int:
    """给文件建独立知识文档并标成 manager, 复现 171 上 add_file 的入口形状.

    Args:
        session: 171 测试库会话.
        space_id: 知识库 ID.
        file_id: 要挂成 manager 的知识库文件 ID.

    Returns:
        新建知识文档 ID.
    """
    document_id = await _last_id(
        session,
        """
        INSERT INTO knowledge_document
          (tenant_id, knowledge_id, lifecycle_status, content_generation)
        VALUES (1, :kid, 'active', 0)
        """,
        {"kid": space_id},
    )
    version_id = await _last_id(
        session,
        """
        INSERT INTO knowledge_document_version
          (document_id, knowledge_file_id, version_no, is_primary)
        VALUES (:did, :fid, 1, 1)
        """,
        {"did": document_id, "fid": file_id},
    )
    await session.execute(
        text("UPDATE knowledge_document SET primary_version_id = :vid WHERE id = :did"),
        {"vid": version_id, "did": document_id},
    )
    await session.execute(
        text(
            """
            UPDATE knowledgefile
            SET status = 2,
                entry_type = 'manager',
                entry_status = 'active',
                reference_document_id = :did
            WHERE id = :fid
            """
        ),
        {"did": document_id, "fid": file_id},
    )
    return document_id


@pytest.mark.asyncio
async def test_promote_transfers_manager_and_deletes_leftover_document_mysql(flow_env, monkeypatch):
    """登记同名更新文件后, 新文件接管原文档, 空文档删除, 已有标签不重复插入."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    document_ids: list[int] = []
    tag_ids: list[int] = []
    captured: dict = {}
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-pm-{suffix}")
            uploader = await _insert_user(session, f"fc-pmu-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-pm-{suffix}", level="department")
            space_ids.append(space_id)
            origin = await _insert_file(
                session,
                space_id=space_id,
                name=f"常用提示词-{suffix}.md",
                user_id=uploader,
            )
            file_ids.append(origin)
            origin_doc = await _seed_manager_document(session, space_id=space_id, file_id=origin)
            document_ids.append(origin_doc)
            await session.execute(
                text("UPDATE knowledgefile SET file_level_path = '/888001', `level` = 1 WHERE id = :id"),
                {"id": origin},
            )
            tag_id = await _last_id(
                session,
                """
                INSERT INTO tag (name, business_type, business_id, user_id, tenant_id, resource_type)
                VALUES (:n, 'tag_library', '1', :uid, 1, 'manual_tag')
                """,
                {"n": f"fc-pm-tag-{suffix}", "uid": uploader},
            )
            tag_ids.append(tag_id)
            await session.execute(
                text(
                    """
                    INSERT INTO taglink (tag_id, resource_id, resource_type, user_id, tenant_id)
                    VALUES (:tid, :rid, 8, :uid, 1)
                    """
                ),
                {"tid": tag_id, "rid": str(origin), "uid": uploader},
            )
            await session.commit()

        async def _fake_add(_request, _login_user, **kwargs):
            captured.update(kwargs)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                new_id = await _insert_file(
                    session,
                    space_id=space_id,
                    name=f"常用提示词-{suffix}-new.md",
                    user_id=uploader,
                )
                leftover_doc = await _seed_manager_document(session, space_id=space_id, file_id=new_id)
                await session.execute(
                    text("UPDATE knowledgefile SET file_name = :n WHERE id = :id"),
                    {"n": f"常用提示词-{suffix}.md", "id": new_id},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO taglink (tag_id, resource_id, resource_type, user_id, tenant_id)
                        VALUES (:tid, :rid, 8, :uid, 1)
                        """
                    ),
                    {"tid": tag_ids[0], "rid": str(new_id), "uid": uploader},
                )
                await session.commit()
            file_ids.append(new_id)
            document_ids.append(leftover_doc)
            return [SimpleNamespace(id=new_id, status=2, file_name=f"常用提示词-{suffix}.md")]

        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_file_correction_service._add_correction_file",
            _fake_add,
        )

        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            created = _body(await _submit(client, origin, "正文写错了"))
            assert created["status_code"] == 200, created
            correction_id = created["data"]["correction_id"]
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            registered = _body(
                await up_client.post(
                    f"/api/v1/knowledge/file-corrections/{correction_id}/update-file",
                    json={"file_path": "tmp/常用提示词1.md"},
                )
            )
            assert registered["status_code"] == 200, registered
            detail = _body(await up_client.get(f"/api/v1/knowledge/file-corrections/{correction_id}"))
            assert detail["status_code"] == 200, detail
            assert detail["data"]["status"] == "approved"

        new_id = int(registered["data"]["id"])
        leftover_id = document_ids[-1]
        async with AsyncSession(engine, expire_on_commit=False) as session:
            new_row = (
                await session.execute(
                    text(
                        """
                        SELECT entry_type, entry_status, reference_document_id, file_level_path, `level`
                        FROM knowledgefile WHERE id = :id
                        """
                    ),
                    {"id": new_id},
                )
            ).one()
            old_row = (
                await session.execute(
                    text(
                        """
                        SELECT entry_type, reference_document_id
                        FROM knowledgefile WHERE id = :id
                        """
                    ),
                    {"id": origin},
                )
            ).one()
            leftover_exists = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_document WHERE id = :id"),
                    {"id": leftover_id},
                )
            ).scalar_one()
            leftover_versions = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_document_version WHERE document_id = :id"),
                    {"id": leftover_id},
                )
            ).scalar_one()
            origin_primary = (
                await session.execute(
                    text(
                        """
                        SELECT v.knowledge_file_id
                        FROM knowledge_document d
                        JOIN knowledge_document_version v ON v.id = d.primary_version_id
                        WHERE d.id = :id
                        """
                    ),
                    {"id": origin_doc},
                )
            ).scalar_one()
            tag_count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM taglink WHERE resource_id = :rid AND tag_id = :tid"),
                    {"rid": str(new_id), "tid": tag_ids[0]},
                )
            ).scalar_one()
            status = (
                await session.execute(
                    text("SELECT status FROM knowledge_file_correction WHERE id = :id"),
                    {"id": correction_id},
                )
            ).scalar_one()
            assert captured.get("allow_duplicate_name") is True
            assert captured.get("allow_duplicate_content") is True
            assert captured.get("parent_id") == 888001
            assert captured.get("award_points") is False
            assert new_row.entry_type == "manager"
            assert new_row.entry_status == "active"
            assert int(new_row.reference_document_id) == int(origin_doc)
            assert new_row.file_level_path == "/888001"
            assert int(new_row.level or 0) == 1
            assert old_row.entry_type is None
            assert old_row.reference_document_id is None
            assert int(leftover_exists) == 0
            assert int(leftover_versions) == 0
            assert int(origin_primary) == int(new_id)
            assert int(tag_count) == 1
            assert str(status) == "approved"
            # 再打一枪: 原文档仍只有新文件当 manager, 空文档不会回来.
            still_manager = (
                await session.execute(
                    text(
                        """
                        SELECT id FROM knowledgefile
                        WHERE reference_document_id = :did AND entry_type = 'manager'
                        """
                    ),
                    {"did": origin_doc},
                )
            ).all()
            assert [int(row[0]) for row in still_manager] == [int(new_id)]
            assert (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_document WHERE id = :id"),
                    {"id": leftover_id},
                )
            ).scalar_one() == 0
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for file_id in file_ids:
                await session.execute(
                    text("DELETE FROM taglink WHERE resource_id = :rid"),
                    {"rid": str(file_id)},
                )
                await session.execute(
                    text("DELETE FROM knowledge_document_version WHERE knowledge_file_id = :id"),
                    {"id": file_id},
                )
            for document_id in document_ids:
                await session.execute(
                    text("DELETE FROM knowledge_document WHERE id = :id"),
                    {"id": document_id},
                )
            for tag_id in tag_ids:
                await session.execute(text("DELETE FROM tag WHERE id = :id"), {"id": tag_id})
            await session.commit()
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)

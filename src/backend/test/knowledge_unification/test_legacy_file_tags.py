"""Legacy tag aliases remain visible and normalize atomically on edit."""

from unittest.mock import Mock

import pytest
from sqlalchemy import insert
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeTagNotExistError
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.database import tenant_filter
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories import knowledge_space_tag_repository as storage
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from test.knowledge_unification import test_direct_delete_scope as fixtures

db = fixtures.db
deletion_tenant = fixtures.deletion_tenant


@pytest.fixture
async def tagged(db, monkeypatch):
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"tag", "taglink"})
    async with db.engine.begin() as connection:
        await connection.run_sync(lambda conn: Tag.metadata.create_all(conn, tables=[Tag.__table__, TagLink.__table__]))
    async with db.sessions() as session:
        await session.execute(
            insert(Tag),
            [
                {"id": 1, "name": "legacy", "business_type": "knowledge_space", "business_id": "1", "tenant_id": 101},
                {
                    "id": 2,
                    "name": "other-space",
                    "business_type": "knowledge_space",
                    "business_id": "2",
                    "tenant_id": 101,
                },
                {"id": 3, "name": "foreign", "business_type": "knowledge_space", "business_id": "1", "tenant_id": 202},
            ],
        )
        await session.execute(
            insert(TagLink),
            [{"tag_id": 1, "resource_id": "31", "resource_type": kind, "tenant_id": 101} for kind in (8, 9)],
        )
        await session.commit()
    monkeypatch.setattr(storage, "get_async_db_session", db.sessions)
    return storage.KnowledgeSpaceTagRepository()


async def links(db):
    async with db.sessions() as session:
        return [(x.resource_type, x.tag_id) for x in (await session.exec(select(TagLink))).all()]


async def test_alias_filter_deduplicates_and_never_crosses_space(db, tagged):
    assert await tagged.list_tagged_file_ids(1, 1) == [31]
    assert await tagged.list_tagged_file_ids(2, 1) == []


async def test_edit_normalizes_both_namespaces_and_clear_does_not_resurrect_legacy(db, tagged):
    await tagged.replace_file_tags(1, 31, [1, 1], user_id=7)
    assert await links(db) == [(8, 1)]
    await tagged.replace_file_tags(1, 31, [], user_id=7)
    assert await links(db) == []


@pytest.mark.parametrize("tag_id", [2, 3, 999])
async def test_invalid_tag_leaves_existing_aliases_intact(db, tagged, tag_id):
    with pytest.raises(KnowledgeTagNotExistError):
        await tagged.replace_file_tags(1, 31, [tag_id], user_id=7)
    assert sorted(await links(db)) == [(8, 1), (9, 1)]


async def test_wrong_space_file_and_folder_cannot_be_retagged(db, tagged):
    for space, file_id in ((2, 31), (1, 10), (1, 999)):
        with pytest.raises(SpaceFileNotFoundError):
            await tagged.replace_file_tags(space, file_id, [], user_id=7)
    assert sorted(await links(db)) == [(8, 1), (9, 1)]


async def test_enrichment_reads_both_namespaces_and_deduplicates(monkeypatch):
    service = object.__new__(KnowledgeSpaceService)
    service.get_logo_share_link = Mock(return_value=None)
    service.login_user = Mock(user_id=7)
    tag = Tag(id=1, name="legacy")
    read = Mock(return_value={"31": [tag, tag]})
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_resource_batch", read
    )
    result = await service._handle_file_folder_extra_info([KnowledgeFile(id=31, knowledge_id=1, file_type=1)])
    assert result[0]["tags"] == [{"id": 1, "name": "legacy"}]
    assert [x.value for x in read.call_args.args[0]] == [8, 9]


async def test_space_tag_picker_includes_legacy_business_and_deletes_owned_links(db, tagged):
    async with db.sessions() as session:
        tag = await session.get(Tag, 1)
        tag.business_type = "knowledge"
        session.add(tag)
        await session.commit()
    assert [tag.id for tag in await tagged.list_space_tags(1)] == [1]
    assert await tagged.tag_belongs_to_space(1, 1)
    assert [tag.id for tag in await tagged.list_space_tags(1, name="legacy")] == [1]
    await tagged.delete_space_tag(1, 1)
    assert await tagged.list_space_tags(1) == []
    assert await links(db) == []


async def test_tag_deletion_rejects_foreign_or_wrong_space_tag(db, tagged):
    for tag_id in (2, 3, 999):
        with pytest.raises(KnowledgeTagNotExistError):
            await tagged.delete_space_tag(1, tag_id)
    assert sorted(await links(db)) == [(8, 1), (9, 1)]

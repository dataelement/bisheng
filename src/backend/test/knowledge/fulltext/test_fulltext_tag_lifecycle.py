from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import request_file_sync_intents
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


async def test_tag_replace_captures_affected_files_before_relationship_changes():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for table in (KnowledgeFulltextOutbox.__table__, KnowledgeFile.__table__, Tag.__table__, TagLink.__table__):
            await connection.run_sync(table.create)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        session.add_all(
            [
                KnowledgeFile(id=21, tenant_id=1, knowledge_id=9, file_name="tagged.pdf", status=2),
                Tag(id=31, tenant_id=1, name="制度", business_type="tag_library", business_id="1"),
                TagLink(
                    id=41,
                    tenant_id=1,
                    tag_id=31,
                    resource_id="21",
                    resource_type=ResourceTypeEnum.SPACE_FILE.value,
                ),
            ]
        )
        await session.flush()
        refs = await TagLibraryTagService._load_files_for_tag_ids(session, [31])
        await session.delete(await session.get(TagLink, 41))
        await request_file_sync_intents(
            session,
            refs,
            trigger_type="tag_replaced",
            multi_tenant_enabled=False,
        )
        await session.commit()

        rows = (await session.exec(select(KnowledgeFulltextOutbox))).all()
        assert [(row.aggregate_id, row.desired_action) for row in rows] == [(21, "sync_current")]
    finally:
        await session.close()
        await engine.dispose()

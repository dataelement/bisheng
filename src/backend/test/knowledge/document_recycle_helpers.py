"""回收集成测试使用的附加表。"""

from sqlalchemy import text

from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem


async def create_recycle_tables(session):
    connection = await session.connection()
    await connection.run_sync(lambda conn: KnowledgeRecycleItem.__table__.create(conn, checkfirst=True))
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS knowledge_space_scope ("
            "id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, space_id INTEGER NOT NULL, "
            "level VARCHAR(32) NOT NULL, owner_type VARCHAR(64) NOT NULL, owner_id INTEGER NOT NULL, "
            "created_by INTEGER NOT NULL DEFAULT 0, create_time DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "update_time DATETIME DEFAULT CURRENT_TIMESTAMP, portal_discovery_enabled BOOLEAN NOT NULL DEFAULT 0)"
        )
    )

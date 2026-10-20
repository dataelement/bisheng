"""Audit and native-session tables are new relative to main and owned by model bootstrap."""

from datetime import datetime

import sqlalchemy as sa

from bisheng.core.database.alembic_helpers.online import create_missing_model_tables
from bisheng.dsh.domain.models.local_session import DshRefreshToken, DshSession
from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from test.dsh.model_audit_fixtures import AUDIT_MODELS

REQUEST_COLUMNS = {
    "model_name_digest",
    "session_origin",
    "parent_conversation_id",
    "message_sources_status",
    "message_sources_ref",
    "audit_status",
    "group_index_pending",
    "group_indexed_status",
    "hierarchy_indexed",
}
GROUP_COLUMNS = {"origin_state", "declared_parent_key", "parent_declaration_missing", "relation_conflict"}


def test_main_upgrade_bootstraps_complete_new_tables_without_incremental_audit_ddl():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for model in (*AUDIT_MODELS, DshSession, DshRefreshToken):
        model.__table__.to_metadata(metadata)
    try:
        with engine.begin() as connection:
            assert len(create_missing_model_tables(connection, metadata)) == 15
            request = DshModelAuditRequest.__table__
            now = datetime(2026, 10, 20)
            item = DshModelAuditRequest(
                request_id="e2e-work110-main",
                tenant_id=2,
                user_id=20,
                model_id=42,
                model_name="Provider / Kept",
                started_at=now,
                create_time=now,
                update_time=now,
            )
            connection.execute(
                request.insert().values({column.name: getattr(item, column.name) for column in request.c})
            )
            assert create_missing_model_tables(connection, metadata) == ()
            inspector = sa.inspect(connection)
            assert REQUEST_COLUMNS <= {row["name"] for row in inspector.get_columns(request.name)}
            assert GROUP_COLUMNS <= {
                row["name"] for row in inspector.get_columns(DshModelAuditConversation.__tablename__)
            }
            assert {
                "ix_dma_request_model",
                "ix_dma_request_name",
                "ix_dma_request_sources",
                "ix_dma_request_status",
                "ix_dma_request_group_pending",
                "ix_dma_request_tree_pending",
            } <= {row["name"] for row in inspector.get_indexes(request.name)}
            assert connection.exec_driver_sql(
                "SELECT request_id, model_name, model_name_digest, audit_status FROM dsh_model_audit_request"
            ).one() == ("e2e-work110-main", "Provider / Kept", None, None)
    finally:
        engine.dispose()

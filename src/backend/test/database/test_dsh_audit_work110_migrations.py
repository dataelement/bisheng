"""The focused audit port keeps its ancestry while admitting deployed audit upgrades."""

from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest

BACKEND = Path(__file__).resolve().parents[2]
REVISIONS = (
    "f062_work110_audit_lookup",
    "f062_work110_audit_sources",
    "f062_work110_audit_groups",
    "f062_work110_audit_tree",
)
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
GROUP_COLUMNS = {
    "origin_state",
    "declared_parent_key",
    "parent_declaration_missing",
    "relation_conflict",
}


def scripts():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "bisheng/core/database/alembic"))
    return ScriptDirectory.from_config(config)


def test_audit_port_preserves_target_ancestry_and_uses_new_revision_ids():
    directory = scripts()
    parent = "f065_dsh_install_policy_default_off"
    for revision in REVISIONS:
        current = directory.get_revision(revision)
        assert current.down_revision == parent
        assert current.dependencies is None
        parent = revision
    assert (
        directory.get_revision("f065_dsh_install_policy_default_off").down_revision == "linsight_skill_default_checked"
    )
    assert directory.get_heads() == ["work110_merge_legacy_audit"]
    assert directory.get_revision("work110_merge_legacy_audit").down_revision == (
        "work110_dsh_local_sessions",
        "f062_dsh_audit_tree",
    )


@pytest.mark.parametrize("fresh", [False, True])
def test_audit_port_ddl_chain_is_idempotent_and_preserves_request_facts(fresh):
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            tables = {}
            for model, additions in (
                (DshModelAuditRequest, REQUEST_COLUMNS),
                (DshModelAuditConversation, GROUP_COLUMNS),
            ):
                if fresh:
                    model.__table__.create(connection)
                    tables[model.__tablename__] = model.__table__
                else:
                    tables[model.__tablename__] = sa.Table(
                        model.__tablename__,
                        sa.MetaData(),
                        *[column._copy() for column in model.__table__.columns if column.name not in additions],
                    )
                    tables[model.__tablename__].create(connection)
            now = datetime(2026, 10, 20)
            item = DshModelAuditRequest(
                request_id="e2e-work110-port",
                tenant_id=2,
                user_id=20,
                model_id=42,
                model_name="Provider / Kept",
                started_at=now,
                create_time=now,
                update_time=now,
            )
            table = tables["dsh_model_audit_request"]
            connection.execute(table.insert().values({column.name: getattr(item, column.name) for column in table.c}))
            with Operations.context(MigrationContext.configure(connection)):
                for _ in range(2):
                    for revision in REVISIONS:
                        scripts().get_revision(revision).module.upgrade()
            assert REQUEST_COLUMNS <= {
                row["name"] for row in sa.inspect(connection).get_columns("dsh_model_audit_request")
            }
            assert GROUP_COLUMNS <= {
                row["name"] for row in sa.inspect(connection).get_columns("dsh_model_audit_conversation")
            }
            assert connection.exec_driver_sql(
                "SELECT request_id, model_name, model_name_digest, audit_status FROM dsh_model_audit_request"
            ).one() == ("e2e-work110-port", "Provider / Kept", None, None)
    finally:
        engine.dispose()

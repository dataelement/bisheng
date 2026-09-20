from pathlib import Path

from sqlalchemy import String

from bisheng.database.models.session import MessageSession, MessageSessionDao


def test_message_session_declares_nullable_entry_flow_and_index():
    column = MessageSession.__table__.c.entry_flow_id

    assert isinstance(column.type, String)
    assert column.type.length == 255
    assert column.nullable is True
    assert "idx_message_session_entry_flow_id" in {index.name for index in MessageSession.__table__.indexes}


def test_legacy_message_session_dao_has_no_f068_entry_points():
    forbidden = {
        "list_by_effective_entry",
        "get_by_chat_and_effective_entry",
        "find_first_by_effective_entry",
        "rehome_by_flows",
    }

    assert forbidden.isdisjoint(vars(MessageSessionDao))


def test_f068_migration_is_ddl_only_and_mounted_on_f066():
    backend_root = Path(__file__).resolve().parents[2]
    migration = backend_root / ("bisheng/core/database/alembic/versions/v3_0_0_beta1_f068_knowledge_chat_entry.py")
    source = migration.read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "f066_pat_data_scope"' in source
    assert "op.add_column" in source
    assert "op.create_index" in source
    assert "op.execute" not in source
    assert "INSERT " not in source.upper()
    assert "UPDATE " not in source.upper()

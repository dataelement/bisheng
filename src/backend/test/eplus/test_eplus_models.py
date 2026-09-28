"""Persistence contract for the E+ robot integration."""

from sqlalchemy import UniqueConstraint

from bisheng.core.database.dialect_helpers import JsonType, LargeText, is_update_time_server_default
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
from bisheng.eplus.domain.models.eplus import (
    EPlusBotConfig,
    EPlusBotSpace,
    EPlusConnectionStatus,
    EPlusConversation,
    EPlusConversationStatus,
    EPlusInboundMessage,
    EPlusInboundStatus,
    EPlusReplyStatus,
    EPlusTurn,
    EPlusTurnStatus,
)

TABLES = (
    EPlusBotConfig.__table__,
    EPlusBotSpace.__table__,
    EPlusInboundMessage.__table__,
    EPlusConversation.__table__,
    EPlusTurn.__table__,
)


def _unique_column_sets(table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _index_column_sets(table) -> set[tuple[str, ...]]:
    return {tuple(column.name for column in index.columns) for index in table.indexes}


def test_eplus_tables_are_discovered_by_schema_bootstrap() -> None:
    assert "bisheng.eplus.domain.models.eplus" in discover_sqlmodel_module_names()
    assert {table.name for table in TABLES} == {
        "eplus_bot_config",
        "eplus_bot_space",
        "eplus_inbound_message",
        "eplus_conversation",
        "eplus_turn",
    }


def test_every_eplus_table_has_a_required_tenant_boundary() -> None:
    for table in TABLES:
        assert "tenant_id" in table.c, table.name
        assert table.c.tenant_id.nullable is False, table.name
        assert table.c.tenant_id.index is True, table.name


def test_audited_tables_use_the_shared_update_time_default() -> None:
    for table in (
        EPlusBotConfig.__table__,
        EPlusInboundMessage.__table__,
        EPlusConversation.__table__,
        EPlusTurn.__table__,
    ):
        update_time = table.c.update_time
        assert update_time.nullable is False, table.name
        assert is_update_time_server_default(update_time.server_default), table.name


def test_bot_config_enforces_assistant_and_bot_one_to_one_per_tenant() -> None:
    table = EPlusBotConfig.__table__
    unique_sets = _unique_column_sets(table)
    assert ("tenant_id", "assistant_id") in unique_sets
    assert ("tenant_id", "bot_id") in unique_sets
    assert ("tenant_id", "enabled", "connection_status") in _index_column_sets(table)
    assert table.c.is_deleted.nullable is False
    assert table.c.is_deleted.default.arg is False
    assert isinstance(table.c.media_host_allowlist.type, JsonType)
    assert isinstance(table.c.secret_ciphertext.type, LargeText)


def test_bot_space_enforces_one_binding_row_per_space() -> None:
    table = EPlusBotSpace.__table__
    assert ("tenant_id", "bot_config_id", "space_id") in _unique_column_sets(table)
    assert ("tenant_id", "space_id") in _index_column_sets(table)


def test_inbound_message_enforces_protocol_idempotency() -> None:
    table = EPlusInboundMessage.__table__
    unique_sets = _unique_column_sets(table)
    assert ("tenant_id", "bot_id", "msgid") in unique_sets
    assert ("tenant_id", "stream_id") in unique_sets
    assert ("tenant_id", "bot_config_id", "status", "received_at") in _index_column_sets(table)
    assert ("tenant_id", "sender_external_id", "status") in _index_column_sets(table)


def test_conversation_and_turn_enforce_stable_ordering() -> None:
    conversation = EPlusConversation.__table__
    turn = EPlusTurn.__table__

    assert ("tenant_id", "bot_config_id", "chat_type", "conversation_key") in _unique_column_sets(conversation)
    assert ("tenant_id", "bot_config_id", "update_time") in _index_column_sets(conversation)
    assert ("tenant_id", "inbound_message_id") in _unique_column_sets(turn)
    assert ("tenant_id", "conversation_id", "turn_seq") in _unique_column_sets(turn)
    assert ("tenant_id", "conversation_id", "scope_version", "turn_seq") in _index_column_sets(turn)
    assert ("tenant_id", "status", "queued_at") in _index_column_sets(turn)
    assert isinstance(turn.c.content_manifest.type, JsonType)
    assert isinstance(turn.c.scope_space_ids.type, JsonType)
    assert isinstance(turn.c.user_text.type, LargeText)
    assert isinstance(turn.c.answer_text.type, LargeText)


def test_statuses_are_portable_string_values_not_database_enums() -> None:
    assert {status.value for status in EPlusConnectionStatus} == {
        "DISABLED",
        "CONNECTING",
        "AUTHENTICATED",
        "RETRYING",
        "TAKEN_OVER",
        "ERROR",
    }
    assert {status.value for status in EPlusInboundStatus} == {
        "RECEIVED",
        "QUEUED",
        "PROCESSING",
        "SUCCEEDED",
        "FAILED",
        "REJECTED_BUSY",
    }
    assert {status.value for status in EPlusReplyStatus} == {
        "NOT_STARTED",
        "STREAMING",
        "FINISHED",
        "SEND_FAILED",
    }
    assert {status.value for status in EPlusConversationStatus} == {"ACTIVE", "CLOSED"}
    assert {status.value for status in EPlusTurnStatus} == {
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
    }

    for table, column_name in (
        (EPlusBotConfig.__table__, "connection_status"),
        (EPlusInboundMessage.__table__, "status"),
        (EPlusInboundMessage.__table__, "reply_status"),
        (EPlusConversation.__table__, "status"),
        (EPlusTurn.__table__, "status"),
    ):
        assert table.c[column_name].type.__class__.__name__ == "String"

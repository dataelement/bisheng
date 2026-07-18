"""Tests for new audit log events: link/promote/delete document version."""
from bisheng.database.models.audit_log import EventType


def test_event_type_link_version_exists():
    assert EventType.LINK_FILE_VERSION.value == "link_file_version"


def test_event_type_promote_version_exists():
    assert EventType.SET_PRIMARY_VERSION.value == "set_primary_version"


def test_event_type_delete_version_exists():
    assert EventType.DELETE_FILE_VERSION.value == "delete_file_version"


def test_audit_log_service_has_version_methods():
    from bisheng.api.services.audit_log import AuditLogService
    assert hasattr(AuditLogService, "link_file_version")
    assert hasattr(AuditLogService, "set_primary_version")
    assert hasattr(AuditLogService, "delete_file_version")


def test_telemetry_service_has_version_wrappers():
    from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
        KnowledgeAuditTelemetryService,
    )
    assert hasattr(KnowledgeAuditTelemetryService, "audit_link_file_version")
    assert hasattr(KnowledgeAuditTelemetryService, "audit_set_primary_version")
    assert hasattr(KnowledgeAuditTelemetryService, "audit_delete_file_version")


from unittest.mock import patch, MagicMock

from bisheng.api.services.audit_log import AuditLogService
from bisheng.database.models.audit_log import EventType, ObjectType


def _fake_user():
    user = MagicMock()
    user.user_id = 1
    user.user_name = "tester"
    return user


def test_link_file_version_calls_knowledge_log_with_correct_args():
    user = _fake_user()
    with patch.object(AuditLogService, "_knowledge_log") as mock_log, \
         patch("bisheng.api.services.audit_log.UserGroupDao") as _:  # _knowledge_log isn't called now, but be safe
        AuditLogService.link_file_version(user, "1.2.3.4", 99, "doc_A#V2")
        mock_log.assert_called_once()
        args, _kwargs = mock_log.call_args
        # _knowledge_log signature: (user, ip_address, event_type, object_type, object_id, object_name, resource_type, resource_id)
        assert args[2] == EventType.LINK_FILE_VERSION
        assert args[3] == ObjectType.FILE
        assert args[4] == "99"
        assert args[5] == "doc_A#V2"


def test_set_primary_version_calls_knowledge_log_with_correct_args():
    user = _fake_user()
    with patch.object(AuditLogService, "_knowledge_log") as mock_log:
        AuditLogService.set_primary_version(user, "1.2.3.4", 42, "doc_B#V3")
        mock_log.assert_called_once()
        args, _ = mock_log.call_args
        assert args[2] == EventType.SET_PRIMARY_VERSION
        assert args[4] == "42"
        assert args[5] == "doc_B#V3"


def test_delete_file_version_calls_knowledge_log_with_correct_args():
    user = _fake_user()
    with patch.object(AuditLogService, "_knowledge_log") as mock_log:
        AuditLogService.delete_file_version(user, "1.2.3.4", 7, "doc_C#V1")
        mock_log.assert_called_once()
        args, _ = mock_log.call_args
        assert args[2] == EventType.DELETE_FILE_VERSION
        assert args[4] == "7"
        assert args[5] == "doc_C#V1"

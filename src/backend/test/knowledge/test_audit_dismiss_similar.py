"""Tests for the DISMISS_SIMILAR_FILE audit event."""
from unittest.mock import patch, MagicMock

from bisheng.api.services.audit_log import AuditLogService
from bisheng.database.models.audit_log import EventType, ObjectType


def test_event_type_dismiss_similar_exists():
    assert EventType.DISMISS_SIMILAR_FILE.value == "dismiss_similar_file"


def test_audit_log_service_has_method():
    assert hasattr(AuditLogService, "dismiss_similar_file")


def test_dismiss_similar_calls_knowledge_log_with_correct_event():
    user = MagicMock()
    user.user_id = 1
    user.user_name = "tester"
    with patch.object(AuditLogService, "_knowledge_log") as mock_log:
        AuditLogService.dismiss_similar_file(user, "1.2.3.4", 42, "doc.pdf")
        mock_log.assert_called_once()
        args, _ = mock_log.call_args
        assert args[2] == EventType.DISMISS_SIMILAR_FILE
        assert args[3] == ObjectType.FILE
        assert args[4] == "42"
        assert args[5] == "doc.pdf"

"""System-operation remark filter: a literal substring of the stored note."""

from bisheng.database.models.audit_log import AuditLogDao
from test.audit.conftest import insert_audit


async def test_note_substring_is_literal_and_intersects_the_action(patch_audit_dao, audit_session):
    insert_audit(audit_session, action="approval.task.approve", note="菜单权限申请")
    insert_audit(audit_session, action="approval.task.reject", note="知识空间加入审批")
    insert_audit(audit_session, action="tenant.mount", note=None)
    insert_audit(audit_session, action="app.publish", note="100%_done")

    rows, total = await AuditLogDao.get_audit_logs([], note="权限")
    assert total == 1
    assert rows[0].action == "approval.task.approve"

    rows, total = await AuditLogDao.get_audit_logs([], event_type="approval.task.reject", note="审批")
    assert total == 1
    assert rows[0].note == "知识空间加入审批"

    # A percent sign is part of the text, not a wildcard that matches every remark.
    rows, total = await AuditLogDao.get_audit_logs([], note="100%")
    assert total == 1
    assert rows[0].action == "app.publish"

    rows, total = await AuditLogDao.get_audit_logs([], note="   ")
    assert total == 4

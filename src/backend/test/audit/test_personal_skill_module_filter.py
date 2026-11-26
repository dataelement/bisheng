"""Personal Skill rows written as system_id=linsight still match 系统.

List, count and export all call AuditLogDao.get_audit_logs, so the module
predicate here is the one the page and the CSV share. New writes use
system_id=system; this only widens the read for the four historical events.
"""

from bisheng.database.models.audit_log import AuditLogDao
from test.audit.conftest import insert_audit

_SKILL_EVENTS = (
    "personal_skill_create",
    "personal_skill_status",
    "personal_skill_delete",
    "personal_skill_overwrite",
)


async def test_system_module_includes_historical_linsight_personal_skills(patch_audit_dao, audit_session):
    for event_type in _SKILL_EVENTS:
        insert_audit(audit_session, system_id="linsight", event_type=event_type)
    insert_audit(audit_session, system_id="system", event_type="personal_skill_create")
    insert_audit(audit_session, system_id="linsight", event_type="create_chat")
    insert_audit(audit_session, system_id="system", event_type="user_login")

    rows, total = await AuditLogDao.get_audit_logs([], system_id="system", event_type="personal_skill_create")
    assert total == 2
    assert {row.system_id for row in rows} == {"linsight", "system"}

    _, total = await AuditLogDao.get_audit_logs([], system_id="system", event_type="personal_skill_status")
    assert total == 1

    rows, total = await AuditLogDao.get_audit_logs([], system_id="system")
    assert total == 6
    assert "create_chat" not in {row.event_type for row in rows}

    _, total = await AuditLogDao.get_audit_logs([], event_type="personal_skill_delete")
    assert total == 1

    _, total = await AuditLogDao.get_audit_logs([], system_id="chat")
    assert total == 0

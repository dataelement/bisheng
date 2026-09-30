"""仅供显式按 ID 操作的诊断和恢复入口, 不被周期扫描调用。"""
from datetime import datetime

from sqlmodel import select

from bisheng.database.models.failed_tuple import FailedTuple
from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocumentRepairState
from bisheng.knowledge.domain.repositories.interfaces.background_task_maintenance_repository import BackgroundTaskMaintenanceRepository
from bisheng.points.domain.models import PointSyncOutbox
from bisheng.shougang_portal_course.domain.models.portal_course import PortalCourseMediaCleanup


class BackgroundTaskMaintenanceRepositoryImpl(BackgroundTaskMaintenanceRepository):
    MODELS = {
        "background": (KnowledgeBackgroundJob, "id", str, ["attempts"]),
        "repair": (KnowledgeDocumentRepairState, "document_id", int, ["attempts", "rebuild_attempts"]),
        "points": (PointSyncOutbox, "id", int, ["retry_count"]),
        "course": (PortalCourseMediaCleanup, "id", str, ["attempt_count"]),
        "openfga": (FailedTuple, "id", int, ["retry_count"]),
    }

    def __init__(self, session):
        self.session = session

    def inspect_or_restore(self, kind: str, ids: list[str], *, restore: bool = False) -> list[dict]:
        model, key, convert, counters = self.MODELS[kind]
        normalized = list(dict.fromkeys(convert(value) for value in ids))
        output = []
        for start in range(0, len(normalized), 200):
            statement = select(model).where(getattr(model, key).in_(normalized[start:start + 200]))
            if restore:
                statement = statement.with_for_update()
            for row in self.session.exec(statement).all():
                before = row.status
                if restore and before == "dead":
                    row.status = "pending"
                    for field in counters:
                        setattr(row, field, 0)
                    for field in ("lease_owner", "lease_until", "next_retry_at", "last_error", "error_message"):
                        if hasattr(row, field):
                            setattr(row, field, None)
                    if hasattr(row, "not_before"):
                        row.not_before = datetime.now()
                    if isinstance(row, KnowledgeBackgroundJob):
                        row.payload = {key: value for key, value in row.payload.items() if key != "wait_deadline"}
                output.append({"id": str(getattr(row, key)), "tenant_id": row.tenant_id, "before": before,
                               "status": row.status, **{field: getattr(row, field) for field in counters},
                               "parent_id": getattr(row, "parent_id", None),
                               "error": getattr(row, "last_error", None) or getattr(row, "error_message", None)})
        return output

"""每批使用短生命周期受管会话，避免复核沿用请求旧事务快照。"""

from collections import Counter, defaultdict
from typing import Any

from sqlmodel import select

from bisheng.common.models.space_channel_member import BusinessTypeEnum, SpaceChannelMember
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import Department
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrant
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.user.domain.models.user_role import UserRole


class PortalSearchContextRepositoryImpl:
    def __init__(self, user_id: int, *, session_factory=get_async_db_session) -> None:
        self.user_id = int(user_id)
        self.session_factory = session_factory
        self.query_counts = Counter()

    async def load(self, kind: str, ids: list[int]) -> dict[int, Any]:
        models = {
            "files": (KnowledgeFile, KnowledgeFile.id),
            "documents": (KnowledgeDocument, KnowledgeDocument.id),
            "entries": (KnowledgeFile, KnowledgeFile.reference_document_id),
            "versions": (KnowledgeDocumentVersion, KnowledgeDocumentVersion.id),
            "primary_versions": (KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id),
            "spaces": (Knowledge, Knowledge.id),
            "scopes": (KnowledgeSpaceScope, KnowledgeSpaceScope.space_id),
            "bindings": (DepartmentKnowledgeSpace, DepartmentKnowledgeSpace.space_id),
            "departments": (Department, Department.id),
            "approvers": (DepartmentAdminGrant, DepartmentAdminGrant.department_id),
            "members": (SpaceChannelMember, SpaceChannelMember.business_id),
            "grants": (DepartmentFileViewGrant, DepartmentFileViewGrant.file_id),
            "admins": (UserRole, UserRole.role_id),
        }
        model, key = models[kind]
        grouped = kind in {"entries", "bindings", "approvers", "admins", "grants", "members"}
        result: dict[int, Any] = defaultdict(list) if grouped else {}
        # 控制 IN 参数量；每个分块只读取缺失 ID，不按空间或文件扇出。
        for start in range(0, len(ids), 500):
            wanted = ids[start : start + 500]
            if kind == "members":
                wanted = [str(item) for item in wanted]
            stmt = select(model).where(key.in_(wanted))
            if kind == "entries":
                stmt = stmt.where(
                    KnowledgeFile.entry_status == "active",
                    KnowledgeFile.entry_type.in_(["manager", "publish", "share"]),
                )
            elif kind == "primary_versions":
                stmt = stmt.where(KnowledgeDocumentVersion.is_primary == True)  # noqa: E712
            elif kind in {"members", "grants"}:
                stmt = stmt.where(model.user_id == self.user_id)
                if kind == "members":
                    stmt = stmt.where(SpaceChannelMember.business_type == BusinessTypeEnum.SPACE)
            elif kind == "admins":
                stmt = stmt.where(UserRole.role_id == AdminRole)
            async with self.session_factory() as session:
                self.query_counts[kind] += 1
                rows = (await session.exec(stmt)).all()
                for row in rows:
                    value = int(getattr(row, key.key))
                    copy = row.model_copy(deep=True)
                    if grouped:
                        result[value].append(copy)
                    else:
                        result[value] = copy
        return dict(result)

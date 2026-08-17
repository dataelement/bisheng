from dataclasses import dataclass, field

from pydantic import BaseModel

from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum

# 公共/部门/科室：库管理员（不含仅所有者）；团队/个人：上传人科室下科室库管理员并集。
ROLE_MANAGED_REVIEW_LEVELS = frozenset({"public", "department", "team_ks"})
ORG_UPLOADER_REVIEW_LEVELS = frozenset({"team", "personal"})


@dataclass(frozen=True)
class ReviewTagSubmitterTarget:
    user_id: int
    knowledge_space_id: int | None = None
    file_id: int | None = None
    file_name: str | None = None
    file_type: str | None = None


@dataclass(frozen=True)
class ReviewTagScope:
    """标签审核可见/可操作范围。

    Attributes:
        full_tenant: 超管/租户管理员，不过滤。
        role_managed_space_ids: 对 public/department/team_ks 具备独立管理员授权的空间
            （can_manage 含部门/用户组继承，但排除「仅凭所有者」）。
        clinic_admin_department_ids: 上述 team_ks 经 department_knowledge_space
            绑到的科室 department_id；用于匹配团队/个人库文件上传人的主部门。
    """

    full_tenant: bool = False
    role_managed_space_ids: frozenset[int] = field(default_factory=frozenset)
    clinic_admin_department_ids: frozenset[int] = field(default_factory=frozenset)

    def has_review_capacity(self) -> bool:
        """是否具备任一审核入口。"""
        return self.full_tenant or bool(self.role_managed_space_ids) or bool(self.clinic_admin_department_ids)

    def allows_space_for_uploader(
        self,
        *,
        space_id: int | None,
        level: str | None,
        uploader_id: int | None,
        uploader_office_department_id: int | None = None,
    ) -> bool:
        """判断某空间+上传人科室组合是否在本 scope 内。

        参数:
            space_id: 文件所在知识空间。
            level: 空间 level。
            uploader_id: 文件上传人（团队/个人路径不再按人集合匹配，保留兼容调用方）。
            uploader_office_department_id: 上传人主部门且 org_level=office 时的部门 ID；
                未打科室标则为 None。
        """
        if self.full_tenant:
            return True
        if space_id is not None and int(space_id) in self.role_managed_space_ids:
            return True
        if not self.clinic_admin_department_ids:
            return False
        level_value = str(level or "")
        if level_value not in ORG_UPLOADER_REVIEW_LEVELS:
            return False
        if uploader_office_department_id is None or int(uploader_office_department_id) <= 0:
            return False
        _ = uploader_id
        return int(uploader_office_department_id) in self.clinic_admin_department_ids


class ApproveOrRejectRequest(BaseModel):
    tag_name: str
    status: ApproveOrRejectEnum
    reject_reason: str = None
    resource_type: TagResourceTypeEnum
    tag_library_id: int | None = None
    knowledge_id: int | None = None

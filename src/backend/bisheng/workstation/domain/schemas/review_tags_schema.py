from dataclasses import dataclass, field

from pydantic import BaseModel

from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum

# 公共/部门/科室：库角色审核；团队/个人：按上传人组织管理员审核。
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
        role_managed_space_ids: 当前用户对 public/department/team_ks 具备 can_manage 的空间。
        org_uploader_ids: 部门管理员所管组织内的用户（按文件上传人匹配）；None 表示非部门管理员路径。
    """

    full_tenant: bool = False
    role_managed_space_ids: frozenset[int] = field(default_factory=frozenset)
    org_uploader_ids: frozenset[int] | None = None

    def has_review_capacity(self) -> bool:
        """是否具备任一审核入口（含部门管理员空组织）。"""
        return self.full_tenant or bool(self.role_managed_space_ids) or self.org_uploader_ids is not None

    def allows_space_for_uploader(self, *, space_id: int | None, level: str | None, uploader_id: int | None) -> bool:
        """判断某空间+上传人组合是否在本 scope 内。"""
        if self.full_tenant:
            return True
        if space_id is not None and int(space_id) in self.role_managed_space_ids:
            return True
        if self.org_uploader_ids is None:
            return False
        level_value = str(level or "")
        if level_value not in ORG_UPLOADER_REVIEW_LEVELS:
            return False
        if uploader_id is None or int(uploader_id) <= 0:
            return False
        return int(uploader_id) in self.org_uploader_ids


class ApproveOrRejectRequest(BaseModel):
    tag_name: str
    status: ApproveOrRejectEnum
    reject_reason: str = None
    resource_type: TagResourceTypeEnum
    tag_library_id: int | None = None
    knowledge_id: int | None = None

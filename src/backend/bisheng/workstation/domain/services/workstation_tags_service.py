from datetime import datetime

from fastapi import Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.common.errcode.tag import (
    ReviewTagNotFoundError,
    ReviewTagPermissionDeniedError,
    ReviewTagSimilarAckRequiredError,
    ReviewTagSpaceOutOfScopeError,
    ReviewTagTypeMismatchError,
    TagNameParamsIsEmptyError,
    TagPageParamsIsError,
    TagPageSizeParamsIsError,
)
from bisheng.common.services.base import BaseService
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl
from bisheng.workstation.domain.schemas.review_tags_schema import (
    ROLE_MANAGED_REVIEW_LEVELS,
    ApproveOrRejectRequest,
    ReviewTagScope,
    ReviewTagSubmitterTarget,
)
from bisheng.workstation.domain.services.review_tag_notification_service import (
    ReviewTagNotificationService,
)


def _parse_fga_user_ref(user_ref: str) -> tuple[str, int] | None:
    """解析 OpenFGA user 字段：user:1 / department:10#member / user_group:5#admin。"""
    raw = str(user_ref or "").strip()
    if not raw:
        return None
    relation_sep = raw.find("#")
    object_part = raw[:relation_sep] if relation_sep >= 0 else raw
    if ":" not in object_part:
        return None
    kind, _, ident = object_part.partition(":")
    if not ident.isdigit():
        return None
    return kind, int(ident)


async def _user_has_independent_manager_grant(user_id: int, space_id: int) -> bool:
    """用户是否对该空间持有独立于 owner 的 manager 授权（口径 2：含部门/用户组）。"""
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    from bisheng.database.models.user_group import UserGroupDao
    from bisheng.permission.domain.services.permission_service import PermissionService

    try:
        fga = await PermissionService._aget_fga()
    except Exception:
        logger.exception("openfga client failed while excluding owner-only review spaces space_id=%s", space_id)
        return False
    if fga is None:
        return False
    try:
        manager_tuples = await fga.read_tuples(relation="manager", object=f"knowledge_space:{int(space_id)}")
    except Exception:
        logger.exception("openfga read manager failed space_id=%s", space_id)
        return False

    memberships = await UserDepartmentDao.aget_user_departments(int(user_id))
    user_dept_ids = {int(row.department_id) for row in (memberships or []) if getattr(row, "department_id", None)}
    group_rows = await UserGroupDao.aget_user_group(int(user_id))
    user_group_ids = {int(row.group_id) for row in (group_rows or []) if getattr(row, "group_id", None)}

    for item in manager_tuples or []:
        parsed = _parse_fga_user_ref(str(item.get("user") or ""))
        if parsed is None:
            continue
        kind, ident = parsed
        if kind == "user" and ident == int(user_id):
            return True
        if kind == "department":
            dept = await DepartmentDao.aget_by_id(ident)
            path = getattr(dept, "path", None) if dept is not None else None
            if path:
                subtree = await DepartmentDao.aget_subtree_ids(path)
                if user_dept_ids.intersection(int(i) for i in (subtree or [])):
                    return True
            elif ident in user_dept_ids:
                return True
        if kind == "user_group" and ident in user_group_ids:
            return True
    return False


async def _exclude_owner_only_space_ids(user_id: int, space_ids: set[int], login_user: UserPayload) -> set[int]:
    """从 can_manage 集合中去掉仅凭所有者进入的空间。"""
    if not space_ids:
        return set()
    from bisheng.permission.domain.services.permission_service import PermissionService

    raw_owner_ids = await PermissionService.list_accessible_ids(
        user_id=user_id,
        relation="owner",
        object_type="knowledge_space",
        login_user=login_user,
    )
    owner_ids = {int(i) for i in (raw_owner_ids or []) if str(i).isdigit()}
    for space_id in space_ids:
        sid = int(space_id)
        if sid in owner_ids:
            continue
        try:
            creator_id = await PermissionService._get_resource_creator("knowledge_space", str(sid))
        except Exception:
            logger.exception("creator fallback failed while excluding owner-only review space_id=%s", sid)
            continue
        if creator_id is not None and int(creator_id) == int(user_id):
            owner_ids.add(sid)
    kept = {int(space_id) for space_id in space_ids if int(space_id) not in owner_ids}
    for space_id in space_ids:
        sid = int(space_id)
        if sid not in owner_ids or sid in kept:
            continue
        if await _user_has_independent_manager_grant(user_id, sid):
            kept.add(sid)
    return kept


async def _resolve_fga_role_managed_space_ids(login_user: UserPayload) -> frozenset[int]:
    """解析 public/department/team_ks 下具备独立管理员授权的空间。

    OpenFGA can_manage 含所有者；按身份排除后只保留独立 manager（含部门/用户组继承）。
    FGA 无结果时回退成员表 admin，不含 creator。
    """
    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, UserRoleEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao
    from bisheng.permission.domain.services.permission_service import PermissionService

    user_id = int(login_user.user_id)
    candidate_ids: list[int] = []
    used_member_fallback = False

    raw_ids = await PermissionService.list_accessible_ids(
        user_id=user_id,
        relation="can_manage",
        object_type="knowledge_space",
        login_user=login_user,
    )
    if raw_ids:
        candidate_ids = [int(i) for i in raw_ids if str(i).isdigit()]

    if not candidate_ids:
        used_member_fallback = True
        managed_members = await SpaceChannelMemberDao.async_get_user_managed_members(user_id)
        for member in managed_members or []:
            if getattr(member, "user_role", None) != UserRoleEnum.ADMIN:
                continue
            business_id = str(getattr(member, "business_id", "") or "").strip()
            if business_id.isdigit():
                candidate_ids.append(int(business_id))

    if not candidate_ids:
        return frozenset()

    if not used_member_fallback:
        candidate_ids = sorted(await _exclude_owner_only_space_ids(user_id, set(candidate_ids), login_user))

    if not candidate_ids:
        return frozenset()

    scope_map = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(candidate_ids)
    role_space_ids: set[int] = set()
    for space_id in candidate_ids:
        scope_row = scope_map.get(space_id)
        level = str(getattr(scope_row, "level", "") or "") if scope_row else ""
        if level in ROLE_MANAGED_REVIEW_LEVELS:
            role_space_ids.add(int(space_id))
    return frozenset(role_space_ids)


async def _clinic_admin_department_ids(role_space_ids: frozenset[int]) -> frozenset[int]:
    """当前人管理的科室库绑定到的科室部门 ID（多库并集）。"""
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao

    if not role_space_ids:
        return frozenset()
    scope_map = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(list(role_space_ids))
    team_ks_ids = [
        int(space_id)
        for space_id in role_space_ids
        if str(getattr(scope_map.get(space_id), "level", "") or "") == "team_ks"
    ]
    if not team_ks_ids:
        return frozenset()
    bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids(team_ks_ids)
    return frozenset(int(row.department_id) for row in (bindings or []) if getattr(row, "department_id", None))


async def resolve_review_tag_scope_for_user(login_user: UserPayload) -> ReviewTagScope:
    """解析当前用户的标签审核范围（不依赖 DB session）。

    Raises:
        ReviewTagPermissionDeniedError: 无任何审核能力时抛出。
    """
    if bool(getattr(login_user, "is_global_super", False)):
        return ReviewTagScope(full_tenant=True)
    is_admin_fn = getattr(login_user, "is_admin", None)
    if callable(is_admin_fn) and is_admin_fn():
        return ReviewTagScope(full_tenant=True)

    has_tenant_admin = getattr(login_user, "has_tenant_admin", None)
    if callable(has_tenant_admin):
        from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id

        tid = get_current_tenant_id()
        if tid is None:
            tid = getattr(login_user, "tenant_id", None)
        if tid is not None and int(tid) != DEFAULT_TENANT_ID and await has_tenant_admin(int(tid)):
            return ReviewTagScope(full_tenant=True)

    role_space_ids = await _resolve_fga_role_managed_space_ids(login_user)
    clinic_dept_ids = await _clinic_admin_department_ids(role_space_ids)
    scope = ReviewTagScope(
        full_tenant=False,
        role_managed_space_ids=role_space_ids,
        clinic_admin_department_ids=clinic_dept_ids,
    )
    if not scope.has_review_capacity():
        raise ReviewTagPermissionDeniedError()
    return scope


async def user_can_review_tags(login_user: UserPayload) -> bool:
    """供 /user/info 等轻量接口判断是否展示标签审核入口。"""
    try:
        await resolve_review_tag_scope_for_user(login_user)
        return True
    except ReviewTagPermissionDeniedError:
        return False


class WorkStationTagsService(BaseService):
    """Workbench tag library and pending review-tag orchestration."""

    def __init__(
        self,
        request: Request,
        session: AsyncSession,
        login_user: UserPayload,
        review_tags_repository: ReviewTagsRepositoryImpl,
    ):
        super().__init__()
        self.request = request
        self.session = session
        self.review_tags_repository = review_tags_repository
        self.login_user = login_user

    async def resolve_review_tag_scope(self) -> ReviewTagScope:
        """解析当前登录用户的标签审核范围。"""
        return await resolve_review_tag_scope_for_user(self.login_user)

    async def resolve_reviewable_space_ids(self) -> set[int] | None:
        """兼容旧调用：全租户返回 None；否则返回 role 管理空间并集（不含上传人维度）。

        新代码应使用 ``resolve_review_tag_scope``。Tag Console 门禁已拆开，勿再依赖本方法做权限判定。
        """
        scope = await self.resolve_review_tag_scope()
        if scope.full_tenant:
            return None
        return set(scope.role_managed_space_ids)

    async def _ensure_knowledge_in_scope(self, knowledge_id: int | None, scope: ReviewTagScope) -> None:
        """通过时校验目标知识库是否在审核范围内。"""
        if scope.full_tenant:
            return
        if knowledge_id is None:
            raise ReviewTagSpaceOutOfScopeError()
        kid = int(knowledge_id)
        if kid in scope.role_managed_space_ids:
            return
        if not scope.clinic_admin_department_ids:
            raise ReviewTagSpaceOutOfScopeError()
        from bisheng.knowledge.domain.models.knowledge_space_scope import (
            KnowledgeSpaceLevelEnum,
            KnowledgeSpaceScopeDao,
        )

        scope_row = await KnowledgeSpaceScopeDao.aget_by_space_id(kid)
        level = str(getattr(scope_row, "level", "") or "") if scope_row else ""
        if level not in (KnowledgeSpaceLevelEnum.TEAM.value, KnowledgeSpaceLevelEnum.PERSONAL.value):
            raise ReviewTagSpaceOutOfScopeError()
        # 科室库管理员可将团队/个人待审写回来源团队/个人库。
        return

    async def delete_review_tag(
        self, tag_name: str, business_type: TagBusinessTypeEnum, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        scope = await self.resolve_review_tag_scope()
        review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id, scope=scope
        )
        if review_tag_list:
            for review_tag in review_tag_list:
                await self.review_tags_repository.delete_review_tag_id(
                    review_tag.id, business_type.value, resource_type, tenant_id
                )
            await self.session.commit()

    @staticmethod
    async def _load_similar_matches_for_tag(
        *,
        tag_name: str,
        tag_library_id: int,
        tenant_id: int,
    ) -> list[dict]:
        import asyncio

        from bisheng.knowledge.domain.services.tag_library_tag_config_service import (
            resolve_review_tag_similarity_threshold_async,
        )
        from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService

        normalized_name = (tag_name or "").strip()
        if not normalized_name:
            return []

        similarity_threshold = await resolve_review_tag_similarity_threshold_async(tenant_id)
        _, similar_rows = await asyncio.to_thread(
            TagLibraryTagService.check_review_tag_similar_in_library_sync,
            tag_name=normalized_name,
            library_id=int(tag_library_id),
            similarity_threshold=similarity_threshold,
        )
        return [
            {
                "name": name,
                "match_kind": kind,
                "score": score,
            }
            for name, kind, score in similar_rows
        ]

    async def ensure_review_tag_similar_acknowledged(
        self,
        *,
        tag_name: str,
        tag_library_id: int,
        tenant_id: int,
        ack_similar: bool,
    ) -> None:
        if ack_similar:
            return
        similar_matches = await self._load_similar_matches_for_tag(
            tag_name=tag_name,
            tag_library_id=tag_library_id,
            tenant_id=tenant_id,
        )
        if not similar_matches:
            return
        raise ReviewTagSimilarAckRequiredError(
            msg="目标库存在相似标签，请确认后再提交",
            tag_name=(tag_name or "").strip(),
            similar_matches=similar_matches,
        )

    async def ensure_review_tags_similar_acknowledged(
        self,
        *,
        tag_names: list[str],
        tag_library_id: int,
        tenant_id: int,
        ack_similar: bool,
    ) -> None:
        if ack_similar:
            return

        seen: set[str] = set()
        blocking: list[dict] = []
        for raw_name in tag_names:
            normalized_name = (raw_name or "").strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            similar_matches = await self._load_similar_matches_for_tag(
                tag_name=normalized_name,
                tag_library_id=tag_library_id,
                tenant_id=tenant_id,
            )
            if similar_matches:
                blocking.append(
                    {
                        "tag_name": normalized_name,
                        "similar_matches": similar_matches,
                    }
                )
        if not blocking:
            return
        preview = "、".join(item["tag_name"] for item in blocking[:5])
        raise ReviewTagSimilarAckRequiredError(
            msg=f"以下标签在目标库中存在相似项，请确认后再提交：{preview}",
            tag_names=[item["tag_name"] for item in blocking],
            items=blocking,
        )

    async def approve_or_reject_review_tag(self, data: ApproveOrRejectRequest, tenant_id: int):
        scope = await self.resolve_review_tag_scope()
        existed_tag_list = []
        submitter_targets = await self.review_tags_repository.list_submitter_notification_targets(
            data.tag_name,
            data.resource_type,
            tenant_id,
            exclude_user_id=self.login_user.user_id,
            scope=scope,
        )
        if data and data.status == ApproveOrRejectEnum.APPROVE:
            if not data.tag_library_id or not data.knowledge_id:
                raise KnowledgeSpaceTagLibraryInvalidError(msg="请选择导入的标签库")
            await self._ensure_knowledge_in_scope(data.knowledge_id, scope)
            from bisheng.database.models.tag import TagBusinessTypeEnum
            from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
                KnowledgeSpaceTagLibraryService,
            )

            review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(
                data.tag_name,
                data.resource_type,
                tenant_id,
                scope=scope,
            )
            if not review_tag_list:
                raise ReviewTagNotFoundError.http_exception()
            await self.ensure_review_tag_similar_acknowledged(
                tag_name=data.tag_name,
                tag_library_id=int(data.tag_library_id),
                tenant_id=tenant_id,
                ack_similar=bool(data.ack_similar),
            )
            bound_ids = await KnowledgeSpaceTagLibraryService.resolve_bound_library_ids(int(data.knowledge_id))
            tag_has_library = any(
                getattr(tag, "business_type", None) == TagBusinessTypeEnum.TAG_LIBRARY.value
                and str(getattr(tag, "business_id", "") or "").strip()
                for tag in (review_tag_list or [])
            )
            require_bound_library = bool(bound_ids) and tag_has_library

            tag_library_service = KnowledgeSpaceTagLibraryService(self.login_user)
            await tag_library_service.append_review_tag(
                library_id=int(data.tag_library_id),
                knowledge_id=int(data.knowledge_id),
                tag_name=data.tag_name,
                review_resource_type=data.resource_type.value,
                require_bound_library=require_bound_library,
            )
            existed_tag_list = await self.approve_tag_to_move_operation(
                data.tag_name,
                data.resource_type,
                tenant_id,
                skip_library_add=True,
                scope=scope,
                target_library_id=int(data.tag_library_id),
            )
            await self.review_tags_repository.approve_review_tag(
                data.tag_name, data.resource_type, tenant_id, scope=scope
            )
            await self.session.commit()
            from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService

            await TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)
        elif data and data.status == ApproveOrRejectEnum.REJECT:
            pending = await self.review_tags_repository.get_review_tag_list_by_tag_name(
                data.tag_name, data.resource_type, tenant_id, scope=scope
            )
            if not pending:
                raise ReviewTagNotFoundError.http_exception()
            await self.review_tags_repository.reject_review_tag(
                data.tag_name,
                data.reject_reason,
                data.resource_type,
                tenant_id,
                scope=scope,
                reviewer_id=getattr(self.login_user, "user_id", None),
            )
            await self.session.commit()
            from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService

            await TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)
        else:
            raise ReviewTagTypeMismatchError.http_exception()

        if data.status == ApproveOrRejectEnum.APPROVE and data.knowledge_id:
            resolved_space_id = int(data.knowledge_id)
            submitter_targets = [
                ReviewTagSubmitterTarget(
                    user_id=target.user_id,
                    knowledge_space_id=resolved_space_id,
                    file_id=target.file_id,
                    file_name=target.file_name,
                    file_type=target.file_type,
                )
                for target in submitter_targets
            ]

        await ReviewTagNotificationService.notify_after_decision(
            sender=self.login_user.user_id,
            sender_user_name=getattr(self.login_user, "user_name", None),
            tag_name=data.tag_name,
            status=data.status,
            submitter_targets=submitter_targets,
            reject_reason=data.reject_reason,
            fallback_knowledge_id=data.knowledge_id,
        )
        return existed_tag_list

    async def approve_tag_to_move_operation(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        *,
        skip_library_add: bool = False,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
        target_library_id: int | None = None,
    ):
        if scope is None:
            # 兼容旧测试：未传 scope 时，space_ids=None 全量；set 视为仅 role 空间。
            if space_ids is None:
                scope = ReviewTagScope(full_tenant=True)
            else:
                scope = ReviewTagScope(role_managed_space_ids=frozenset(int(i) for i in space_ids))
        review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id, scope=scope
        )
        existed_tag_list = []
        if not review_tag_list:
            raise ReviewTagNotFoundError.http_exception()
        # Approve hard-deletes the review_tag row, so the audit trail has to be
        # stamped onto the tag row during the move (F079).
        reviewer_id = getattr(self.login_user, "user_id", None)
        reviewed_at = datetime.now()

        # Checked once, before the loop, and against the *chosen* library.
        #
        # Registering the name into that library already left a row there, so a
        # per-row "does it exist" check would now match on the first iteration
        # and skip every remaining row — dropping the file links of every space
        # after the first. A row that already carries a reviewer is the only
        # real "approved earlier" case.
        already_approved = await self.review_tags_repository.query_existed_tag_by_review_tag(
            review_tag_list[0],
            target_library_id=target_library_id,
        )
        if already_approved is not None and already_approved.reviewer_id is not None:
            logger.error(f"tag {tag_name} already existed")
            return list(review_tag_list)

        for review_tag in review_tag_list:
            review_tag_link = await self.review_tags_repository.query_review_tag_link_list_by_tag_id(
                review_tag.id, tenant_id
            )
            if not review_tag_link:
                review_tag_link = []
            if not scope.full_tenant:
                filtered_links = []
                for link in review_tag_link:
                    if await self.review_tags_repository.link_in_review_scope(link, review_tag, tenant_id, scope):
                        filtered_links.append(link)
                review_tag_link = filtered_links
            await self.review_tags_repository.approve_tag_to_move(
                review_tag,
                review_tag_link,
                skip_library_add=skip_library_add,
                reviewer_id=reviewer_id,
                review_time=reviewed_at,
                target_library_id=target_library_id,
            )
        return existed_tag_list

    async def create_tag_library_by_name(self, tag_name: str, tenant_id: int):
        if not tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        await self.review_tags_repository.create_tag_library_by_tag(tag_name, tenant_id, TagResourceTypeEnum.SYSTEM_TAG)
        await self.session.commit()

    async def update_tag_library_by_name(
        self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        if not tag_name or not original_tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        if resource_type == TagResourceTypeEnum.SYSTEM_TAG or resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
            await self.review_tags_repository.update_tag_library_by_tag(
                original_tag_name, tag_name, resource_type, tenant_id
            )
        elif resource_type == TagResourceTypeEnum.MANUAL_TAG:
            await self.review_tags_repository.update_tag_library_by_manual_tag(
                original_tag_name, tag_name, resource_type, tenant_id
            )
        await self.session.commit()

    async def delete_tag_library_by_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        if not tag_name or not resource_type:
            raise TagNameParamsIsEmptyError.http_exception()
        if resource_type == TagResourceTypeEnum.SYSTEM_TAG or resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
            await self.review_tags_repository.delete_tag_library_by_tag(tag_name, resource_type, tenant_id)
        elif resource_type == TagResourceTypeEnum.MANUAL_TAG:
            await self.review_tags_repository.delete_tag_library_by_manual_tag(tag_name, resource_type, tenant_id)
        await self.session.commit()

    async def list_tag_library_by_name(self, keyword: str, tenant_id: int):
        tags_list, result_dict = await self.review_tags_repository.get_list_tag_library_by_name(keyword, tenant_id)
        result_list = []
        if tags_list and len(tags_list) > 0:
            for tag in tags_list:
                tag_obj = await self.review_tags_repository.get_tag_info_by_tag(
                    tag, result_dict.get(tag, TagResourceTypeEnum.AI_AUTO_TAG), tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        return result_list

    async def list_review_tag_by_page(self, page: int, page_size: int, tenant_id: int, keyword: str = ""):
        scope = await self.resolve_review_tag_scope()
        if not page or page < 1:
            raise TagPageParamsIsError.http_exception()
        if not page_size or page_size < 1:
            raise TagPageSizeParamsIsError.http_exception()

        normalized_keyword = (keyword or "").strip()
        group_tag_list = await self.review_tags_repository.get_review_tag_group_list_by_page(
            page, page_size, tenant_id, normalized_keyword, scope=scope
        )
        result_list = []
        if group_tag_list and len(group_tag_list) > 0:
            for group_tag in group_tag_list:
                tag_obj = await self.review_tags_repository.get_review_tag_resource_info_by_tag(
                    group_tag["name"], group_tag["resource_type"], tenant_id, scope=scope
                )
                if tag_obj:
                    result_list.append(tag_obj)
        total_count = await self.review_tags_repository.get_review_tag_group_count_by_page(
            tenant_id, normalized_keyword, scope=scope
        )
        return {"data": result_list or [], "total": total_count or 0}

    async def list_all_tags_library_by_page(self, keyword: str, page: int, page_size: int, tenant_id: int):
        if not page or page < 1:
            raise TagPageParamsIsError.http_exception()
        if not page_size or page_size < 1:
            raise TagPageSizeParamsIsError.http_exception()
        tag_list = await self.review_tags_repository.list_all_tags_by_page(page, page_size, keyword, tenant_id)
        result_list = []
        result_list.clear()
        if tag_list and len(tag_list) > 0:
            for tag in tag_list:
                tag_obj = await self.review_tags_repository.get_tag_info_by_tag(
                    tag["name"], tag["resource_type"], tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        data_list = await self.list_tag_library_by_keyword(keyword, tenant_id)
        if len(result_list) < page_size and data_list and len(data_list) > 0:
            count = min(page_size - len(result_list), len(data_list))
            result_list.extend(data_list[:count])

        total_count = await self.review_tags_repository.query_all_tag_library_count_by_page(keyword, tenant_id)
        total = int(total_count or 0) + len(data_list or [])
        return {"data": result_list or [], "total": total}

    async def list_tag_library_by_keyword(self, keyword: str, tenant_id: int):
        tags_list, result_dict = await self.review_tags_repository.get_not_exist_system_tag_by_name(keyword, tenant_id)
        result_list = []
        if tags_list and len(tags_list) > 0:
            for tag in tags_list:
                tag_obj = await self.review_tags_repository.get_not_exist_tag_info_by_tag(
                    tag, result_dict.get(tag, TagResourceTypeEnum.AI_AUTO_TAG), tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        return result_list

    async def check_review_tag_similar_in_library(
        self,
        *,
        tag_name: str,
        tag_library_id: int,
        tenant_id: int,
    ):
        import asyncio

        from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
        from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibraryDao
        from bisheng.knowledge.domain.services.tag_library_tag_config_service import (
            resolve_review_tag_similarity_threshold_async,
        )
        from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
        from bisheng.workstation.domain.schemas.review_tags_schema import (
            ReviewTagSimilarCheckResponse,
            ReviewTagSimilarMatchItem,
        )

        normalized_name = (tag_name or "").strip()
        if not normalized_name:
            raise TagNameParamsIsEmptyError.http_exception()
        if not tag_library_id or int(tag_library_id) <= 0:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="请选择导入的标签库")

        library = await KnowledgeSpaceTagLibraryDao.aget(int(tag_library_id))
        if not library:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签库不存在")
        if int(library.tenant_id) != int(tenant_id):
            raise KnowledgeSpaceTagLibraryInvalidError(msg="该标签库未关联此知识空间")

        similarity_threshold = await resolve_review_tag_similarity_threshold_async(tenant_id)
        exact_rows, similar_rows = await asyncio.to_thread(
            TagLibraryTagService.check_review_tag_similar_in_library_sync,
            tag_name=normalized_name,
            library_id=int(tag_library_id),
            similarity_threshold=similarity_threshold,
        )
        return ReviewTagSimilarCheckResponse(
            exact_matches=[
                ReviewTagSimilarMatchItem(name=name, match_kind=kind, score=score)
                for name, kind, score in exact_rows
            ],
            similar_matches=[
                ReviewTagSimilarMatchItem(name=name, match_kind=kind, score=score)
                for name, kind, score in similar_rows
            ],
            similarity_threshold=similarity_threshold,
        )

    async def check_review_tag_similar_in_library_batch(
        self,
        *,
        tag_names: list[str],
        tag_library_id: int,
        tenant_id: int,
    ):
        import asyncio

        from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
        from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibraryDao
        from bisheng.knowledge.domain.services.tag_library_tag_config_service import (
            resolve_review_tag_similarity_threshold_async,
        )
        from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
        from bisheng.workstation.domain.schemas.review_tags_schema import (
            ReviewTagSimilarBatchCheckResponse,
            ReviewTagSimilarBatchItem,
            ReviewTagSimilarMatchItem,
        )
        from bisheng.workstation.domain.schemas.tag_console_schema import MAX_BATCH_SIZE

        if not tag_library_id or int(tag_library_id) <= 0:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="请选择导入的标签库")
        if not tag_names:
            raise TagNameParamsIsEmptyError.http_exception()
        if len(tag_names) > MAX_BATCH_SIZE:
            raise TagPageSizeParamsIsError.http_exception()

        library = await KnowledgeSpaceTagLibraryDao.aget(int(tag_library_id))
        if not library:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签库不存在")
        if int(library.tenant_id) != int(tenant_id):
            raise KnowledgeSpaceTagLibraryInvalidError(msg="该标签库未关联此知识空间")

        similarity_threshold = await resolve_review_tag_similarity_threshold_async(tenant_id)
        rows = await asyncio.to_thread(
            TagLibraryTagService.check_review_tag_similar_in_library_batch_sync,
            tag_names=tag_names,
            library_id=int(tag_library_id),
            similarity_threshold=similarity_threshold,
        )
        items: list[ReviewTagSimilarBatchItem] = []
        similar_tag_count = 0
        for tag_name, exact_rows, similar_rows in rows:
            if similar_rows:
                similar_tag_count += 1
            items.append(
                ReviewTagSimilarBatchItem(
                    tag_name=tag_name,
                    exact_matches=[
                        ReviewTagSimilarMatchItem(name=name, match_kind=kind, score=score)
                        for name, kind, score in exact_rows
                    ],
                    similar_matches=[
                        ReviewTagSimilarMatchItem(name=name, match_kind=kind, score=score)
                        for name, kind, score in similar_rows
                    ],
                )
            )
        return ReviewTagSimilarBatchCheckResponse(
            items=items,
            similar_tag_count=similar_tag_count,
            similarity_threshold=similarity_threshold,
        )

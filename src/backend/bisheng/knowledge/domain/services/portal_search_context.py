"""门户检索的请求内资料；加载与安全刷新按阶段隔离。"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from copy import deepcopy
from typing import Any

from loguru import logger

from bisheng.knowledge.domain.repositories.interfaces.portal_search_context_repository import (
    PortalSearchContextRepository,
)
from bisheng.permission.domain.services.permission_read_context import PermissionReadContext


class PortalSearchContext:
    def __init__(
        self,
        *,
        tenant_id: int,
        user_id: int,
        routing_version: int,
        space_ids: list[int],
        repository: PortalSearchContextRepository,
    ) -> None:
        self.identity = (int(tenant_id), int(user_id), int(routing_version))
        self.space_ids = frozenset(int(i) for i in space_ids)
        self.filter_signature: str | None = None
        self.repository = repository
        self.phase = "candidates"
        self.phase_started = time.monotonic()
        self.data: dict[str, dict[int, Any]] = {}
        self.loaded: dict[str, set[int]] = {}
        self.lock = asyncio.Lock()
        self.stats = Counter()
        self.permissions = PermissionReadContext(tenant_id=tenant_id, user_id=user_id)
        self.permissions.department_loader = lambda ids: self.ensure("departments", ids)
        self.closed = False

    def require_identity(self, *, tenant_id: int, user_id: int, routing_version: int) -> None:
        if self.identity != (int(tenant_id), int(user_id), int(routing_version)):
            raise ValueError("检索上下文身份或路由不一致")

    def bind_filters(self, signature: str) -> None:
        if self.filter_signature is not None and self.filter_signature != signature:
            raise ValueError("检索上下文筛选范围发生变化")
        self.filter_signature = signature

    def seed(self, kind: str, rows: dict[int, Any], *, requested=()) -> None:
        if self.closed:
            raise RuntimeError("检索上下文已关闭")
        safe = {}
        for key, value in rows.items():
            items = value if isinstance(value, list) else [value]
            if any(getattr(item, "tenant_id", self.identity[0]) not in {None, self.identity[0]} for item in items):
                continue
            safe[int(key)] = deepcopy(value)
        self.data.setdefault(kind, {}).update(safe)
        self.loaded.setdefault(kind, set()).update(map(int, requested))
        self.loaded[kind].update(safe)
        if kind in {"files", "spaces", "scopes"}:
            setattr(self.permissions, kind, {key: self.data[kind].get(key) for key in self.loaded[kind]})
        if kind == "versions":
            self.seed(
                "primary_versions",
                {
                    int(row.knowledge_file_id): row
                    for row in safe.values()
                    if getattr(row, "is_primary", False) and row.knowledge_file_id is not None
                },
            )
        elif kind == "primary_versions":
            # 按文件查到的主版本也供分发信息按版本 ID 读取复用。
            self.data.setdefault("versions", {}).update({int(row.id): row for row in safe.values()})
            self.loaded.setdefault("versions", set()).update(int(row.id) for row in safe.values())

    async def ensure(self, kind: str, ids, *, loader=None) -> dict[int, Any]:
        wanted = set(int(i) for i in ids)
        async with self.lock:
            if self.closed:
                raise RuntimeError("检索上下文已关闭")
            missing = sorted(wanted - self.loaded.get(kind, set()))
            self.stats[f"{kind}.cache_hits"] += len(wanted) - len(missing)
            if missing:
                started = time.monotonic()
                rows = await (loader(missing) if loader else self.repository.load(kind, missing))
                self.seed(kind, rows, requested=missing)
                self.stats[f"{kind}.batches"] += (len(missing) + 499) // 500
                self.stats[f"{kind}.loaded_ids"] += len(missing)
                self.stats[f"{kind}.elapsed_ms"] += int((time.monotonic() - started) * 1000)
            return deepcopy({key: value for key, value in self.data.get(kind, {}).items() if key in wanted})

    def report(self) -> None:
        logger.info(
            "portal_search_context phase={} elapsed_ms={} data_stats={} permission_stats={}",
            self.phase,
            int((time.monotonic() - self.phase_started) * 1000),
            dict(self.stats),
            dict(self.permissions.stats),
        )

    async def start_validation_phase(self, phase: str) -> None:
        # 等待旧阶段数据库读取，并回收旧阶段任务，迟到结果不能写入新阶段。
        async with self.lock:
            if self.closed:
                raise RuntimeError("检索上下文已关闭")
            await self.permissions.close()
            self.report()
            self.phase = phase
            self.phase_started = time.monotonic()
            self.data.clear()
            self.loaded.clear()
            self.stats.clear()
            self.permissions = PermissionReadContext(tenant_id=self.identity[0], user_id=self.identity[1])
            self.permissions.department_loader = lambda ids: self.ensure("departments", ids)

    async def close(self) -> None:
        self.closed = True
        await self.permissions.close()
        self.report()
        self.data.clear()
        self.loaded.clear()

    async def organization(self, files):
        ids = {int(file.knowledge_id) for file in files}
        spaces = await self.ensure("spaces", ids)
        scopes = await self.ensure("scopes", ids)
        bindings = await self.ensure("bindings", ids)
        department_ids = {int(row.department_id) for rows in bindings.values() for row in rows}
        departments = await self.ensure("departments", department_ids)
        return spaces, scopes, bindings, departments

    async def rows(self, kind, ids):
        return list((await self.ensure(kind, ids)).values())

    async def source_metadata(self, space_ids):
        from bisheng.department.domain.services.department_display_service import (
            get_department_display_name,
            normalize_department_short_name,
        )
        from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

        spaces = await self.ensure("spaces", space_ids)
        bindings = await self.ensure("bindings", space_ids)
        departments = await self.ensure(
            "departments", {int(row.department_id) for group in bindings.values() for row in group}
        )
        result = {}
        for sid, space in spaces.items():
            if space.type != KnowledgeTypeEnum.SPACE.value:
                continue
            # 与原来源外连接相同：无绑定时保留空间，重复绑定按返回顺序覆盖。
            for binding in bindings.get(sid) or [None]:
                department = departments.get(int(binding.department_id)) if binding else None
                name = str(getattr(department, "name", "") or "")
                short = getattr(department, "short_name", None)
                result[sid] = (
                    str(space.name or sid),
                    name,
                    normalize_department_short_name(short),
                    get_department_display_name(name, short),
                )
        return result

    async def phase_user(self, user):
        """复核不能沿用 LoginUser 已缓存的数据库管理员角色。"""
        from bisheng.database.constants import AdminRole

        if not isinstance(getattr(user, "user_role", None), list):
            return user
        admins = await self.ensure("admins", [AdminRole])
        admin_ids = {int(row.user_id) for rows in admins.values() for row in rows}
        copied = deepcopy(user)
        copied.user_role = [role for role in copied.user_role if role != AdminRole]
        if int(user.user_id) in admin_ids:
            copied.user_role.append(AdminRole)
        copied.__dict__.pop("_check_admin", None)
        return copied

    async def display_permissions(self, owner, file):
        from bisheng.knowledge.domain.services.knowledge_space_service import _SPACE_MEMBER_ROLE_TO_RELATION
        from bisheng.permission.domain.knowledge_space_permission_template import default_permission_ids_for_relation
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        sid, fid = int(file.knowledge_id), int(file.id)
        login_user = await self.phase_user(owner.login_user)
        members = await self.ensure("members", [sid])
        permissions, matched = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            "knowledge_file",
            fid,
            lineage=owner._build_item_lineage(file, sid),
            nearest_binding_wins=True,
            return_match_metadata=True,
            use_permission_level_fallback=False,
            read_context=self.permissions,
        )
        if not matched:
            for member in members.get(sid, [])[:1]:
                if member.is_active:
                    permissions.update(
                        default_permission_ids_for_relation(_SPACE_MEMBER_ROLE_TO_RELATION.get(member.user_role, ""))
                    )
        permissions.update(self.permissions.public_permissions([("knowledge_space", sid)], portal=True) or set())
        return permissions

    async def approvers(self, department_ids):
        from bisheng.database.constants import AdminRole
        from bisheng.knowledge.domain.services.department_file_view_access_service import (
            DepartmentFileViewAccessService,
        )

        departments = await self.ensure("departments", department_ids)
        hierarchy = DepartmentFileViewAccessService.department_hierarchy(department_ids, departments)
        grants = await self.ensure("approvers", {i for rows in hierarchy.values() for i in rows})
        admins = await self.ensure("admins", [AdminRole])
        return DepartmentFileViewAccessService.approvers_from_rows(
            hierarchy,
            [row for rows in grants.values() for row in rows],
            [row for rows in admins.values() for row in rows],
        )

    async def active_grants(self, *, tenant_id, user_id, resources):
        from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrantStatus

        if (int(tenant_id), int(user_id)) != self.identity[:2]:
            raise ValueError("授权资料身份不一致")
        rows = await self.ensure("grants", [fid for _, fid in resources])
        return {
            (int(row.space_id), int(row.file_id)): row
            for group in rows.values()
            for row in group
            if row.status == DepartmentFileViewGrantStatus.ACTIVE
            and resources.get((int(row.space_id), int(row.file_id))) == int(row.department_id)
        }

    async def filter_visible(self, owner, files):
        """复用组织资料，具体权限仍由原授权器和部门访问服务计算。"""
        if not files:
            return []
        from types import SimpleNamespace

        from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
        from bisheng.knowledge.domain.services.department_file_view_access_service import (
            DepartmentFileViewAccessService,
        )
        from bisheng.knowledge.domain.services.knowledge_space_service import _SPACE_MEMBER_ROLE_TO_RELATION
        from bisheng.permission.domain.knowledge_space_permission_template import default_permission_ids_for_relation
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        self.require_identity(
            tenant_id=owner.login_user.tenant_id, user_id=owner.login_user.user_id, routing_version=self.identity[2]
        )
        login_user = await self.phase_user(owner.login_user)
        self.seed("files", {int(file.id): file for file in files})
        spaces, scopes, bindings, departments = await self.organization(files)
        resources = DepartmentFileViewAccessService.build_resources(files, spaces, scopes, bindings, departments)
        public = {
            sid
            for sid in spaces
            if owner._space_level_value(
                getattr(spaces[sid], "space_level", None) or getattr(scopes.get(sid), "level", None)
            )
            == "public"
        }
        guarded = {fid for fid, resource in resources.items() if resource.applicable} | {
            int(file.id)
            for file in files
            if getattr(owner, "_portal_space_kind_map", {}).get(int(file.knowledge_id)) in {"department", "clinic"}
        }
        valid = []
        discovery = getattr(owner, "_portal_discovery_result", None)
        full_spaces = (
            set(discovery.discoverable_space_ids + discovery.explicitly_visible_space_ids) if discovery else set()
        )
        for file in files:
            sid, fid = int(file.knowledge_id), int(file.id)
            if (
                sid not in self.space_ids
                or sid not in spaces
                or getattr(spaces[sid], "state", None) == KnowledgeState.DELETING.value
            ):
                continue
            if spaces[sid].type != KnowledgeTypeEnum.SPACE.value:
                continue
            if sid in getattr(owner, "_portal_grant_parent_space_ids", set()) and sid not in full_spaces:
                if fid not in getattr(owner, "_portal_explicit_file_ids", set()):
                    continue
            valid.append(file)
        guarded_files = [file for file in valid if int(file.id) in guarded and int(file.knowledge_id) not in public]
        decisions = {}
        original = owner.department_file_view_access_service
        if guarded_files and original is not None:
            # 注入预加载资料，重用原有所有者/审批人/模板/单文件授权决策。
            async def resource_loader(batch):
                return {int(file.id): resources[int(file.id)] for file in batch}

            service = (
                DepartmentFileViewAccessService(
                    grant_repository=SimpleNamespace(list_active_by_user_and_files=self.active_grants),
                    resource_loader=resource_loader,
                    approver_resolver=self.approvers,
                    permission_read_context=self.permissions,
                )
                if isinstance(original, DepartmentFileViewAccessService)
                else original
            )
            try:
                decisions = await service.evaluate_files(login_user=login_user, files=guarded_files)
            except Exception:
                logger.exception("portal context batch access failed; retrying isolated spaces")
                for sid in sorted({int(file.knowledge_id) for file in guarded_files}):
                    batch = [file for file in guarded_files if int(file.knowledge_id) == sid]
                    try:
                        decisions.update(await service.evaluate_files(login_user=login_user, files=batch))
                    except Exception:
                        logger.exception("portal context space access failed: space_id={}", sid)
        ordinary = [file for file in valid if int(file.id) not in guarded and int(file.knowledge_id) not in public]
        members = await self.ensure("members", {int(file.knowledge_id) for file in ordinary})

        async def check(file):
            sid = int(file.knowledge_id)
            permissions, matched = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                "knowledge_file",
                int(file.id),
                lineage=owner._build_item_lineage(file, sid),
                nearest_binding_wins=True,
                return_match_metadata=True,
                read_context=self.permissions,
            )
            if not matched:
                for member in members.get(sid, [])[:1]:
                    if member.is_active:
                        permissions.update(
                            default_permission_ids_for_relation(
                                _SPACE_MEMBER_ROLE_TO_RELATION.get(member.user_role, "")
                            )
                        )
            permissions.update(self.permissions.public_permissions([("knowledge_space", sid)], portal=True) or set())
            return int(file.id), permissions

        tasks = [asyncio.create_task(check(file)) for file in ordinary]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failed_spaces = set()
            ordinary_permissions = {}
            for file, result in zip(ordinary, results):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    failed_spaces.add(int(file.knowledge_id))
                    logger.warning(
                        "portal context ordinary access failed: space_id={} error={}",
                        file.knowledge_id,
                        type(result).__name__,
                    )
                else:
                    ordinary_permissions[result[0]] = result[1]
            for file in ordinary:
                if int(file.knowledge_id) in failed_spaces:
                    ordinary_permissions.pop(int(file.id), None)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for name in ("_portal_file_download_map", "_portal_file_access_decision_map", "_entry_permission_ids_by_file"):
            if not hasattr(owner, name):
                setattr(owner, name, {})
        visible = []
        for file in valid:
            fid, sid = int(file.id), int(file.knowledge_id)
            if sid in public:
                permissions = self.permissions.public_permissions([("knowledge_space", sid)], portal=True) or set()
            elif fid in guarded:
                decision = decisions.get(fid)
                if decision is None or decision.status not in {"allowed", "approval_required"}:
                    continue
                owner._portal_file_access_decision_map[fid] = decision
                permissions = ({"view_file"} if decision.status == "allowed" else set()) | (
                    {"download_file"} if decision.can_download else set()
                )
            else:
                permissions = ordinary_permissions.get(fid, set())
                if "view_file" not in permissions:
                    continue
            owner._portal_file_download_map[fid] = "download_file" in permissions
            if fid in ordinary_permissions:
                owner._entry_permission_ids_by_file[fid] = permissions
            visible.append(file)
        return visible

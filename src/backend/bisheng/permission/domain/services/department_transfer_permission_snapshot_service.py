from __future__ import annotations

from typing import Any

from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.services.permission_relation_binding_service import (
    PermissionRelationBindingService,
)
from bisheng.permission.domain.services.permission_service import PermissionService

_KNOWLEDGE_RESOURCE_TYPES = frozenset({"knowledge_space", "folder", "knowledge_file"})
_DIRECT_RELATIONS = frozenset({"viewer", "editor", "manager"})
_INCLUDED_SCOPE_LEVELS = frozenset({"public", "department", "team", "team_ks"})


class DepartmentTransferPermissionSnapshotService:
    def __init__(
        self,
        *,
        session,
        repository,
        source_repository=None,
        binding_service: PermissionRelationBindingService | None = None,
        fga_client=None,
    ):
        self.session = session
        self.repository = repository
        self.source_repository = source_repository or repository
        self.binding_service = binding_service or PermissionRelationBindingService()
        self.fga_client = fga_client

    async def capture(self, event) -> None:
        user_id = int(event.user_id)
        tenant_id = int(event.tenant_id or 1)
        candidates: dict[tuple[str, str, str], dict[str, Any]] = {}

        for binding in await self.binding_service.get_bindings():
            if not self._is_target_binding(binding, user_id):
                continue
            signature = (
                str(binding["resource_type"]),
                str(binding["resource_id"]),
                str(binding["relation"]),
            )
            candidate = candidates.setdefault(signature, {"sources": set()})
            candidate["sources"].add("binding")
            candidate["binding_key"] = binding.get("key")
            candidate["model_id"] = binding.get("model_id")

        fga = self.fga_client or await PermissionService._aget_fga()
        if fga is None:
            raise RuntimeError("openfga client unavailable during department transfer snapshot")
        for raw_tuple in await fga.read_tuples(user=f"user:{user_id}"):
            tuple_key = raw_tuple.get("key", raw_tuple)
            if tuple_key.get("user") != f"user:{user_id}":
                continue
            relation = str(tuple_key.get("relation") or "")
            if relation not in _DIRECT_RELATIONS:
                continue
            object_value = str(tuple_key.get("object") or "")
            if ":" not in object_value:
                continue
            resource_type, resource_id = object_value.split(":", 1)
            if resource_type not in _KNOWLEDGE_RESOURCE_TYPES:
                continue
            signature = (resource_type, resource_id, relation)
            candidates.setdefault(signature, {"sources": set()})["sources"].add("openfga")

        resources = {(kind, resource_id) for kind, resource_id, _ in candidates}
        contexts = await self.source_repository.resolve_resource_contexts(resources=resources)
        for (resource_type, resource_id, relation), candidate in candidates.items():
            context = contexts.get((resource_type, resource_id))
            status, error = self._scope_status(
                context=context,
                user_id=user_id,
                resource_type=resource_type,
            )
            snapshot = {
                "sources": sorted(candidate["sources"]),
                "binding_key": candidate.get("binding_key"),
                "model_id": candidate.get("model_id"),
            }
            await self.repository.upsert_item(
                tenant_id=tenant_id,
                event_id=int(event.id),
                item_key=self.knowledge_item_key(resource_type, resource_id, relation),
                item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                root_space_id=context.get("root_space_id") if context else None,
                relation=relation,
                source_ref=candidate.get("binding_key"),
                snapshot=snapshot,
                status=status,
                last_error=error,
            )

        memberships = await self.source_repository.list_active_memberships(user_id=user_id)
        membership_space_ids = {
            ("knowledge_space", str(member.business_id))
            for member in memberships
            if self._enum_value(member.user_role) != UserRoleEnum.CREATOR.value
            and (member.membership_source or "manual") in {"manual", "rebac"}
        }
        missing_membership_contexts = membership_space_ids - set(contexts)
        if missing_membership_contexts:
            contexts.update(
                await self.source_repository.resolve_resource_contexts(
                    resources=missing_membership_contexts,
                )
            )
        for member in memberships:
            if self._enum_value(member.user_role) == UserRoleEnum.CREATOR.value:
                continue
            if (member.membership_source or "manual") not in {"manual", "rebac"}:
                continue
            resource_id = str(member.business_id)
            context = contexts.get(("knowledge_space", resource_id))
            status, error = self._scope_status(
                context=context,
                user_id=user_id,
                resource_type="knowledge_space",
            )
            await self.repository.upsert_item(
                tenant_id=tenant_id,
                event_id=int(event.id),
                item_key=self.space_membership_item_key(resource_id),
                item_type=DepartmentTransferCleanupItemType.SPACE_MEMBERSHIP,
                user_id=user_id,
                resource_type="knowledge_space",
                resource_id=resource_id,
                root_space_id=context.get("root_space_id") if context else None,
                relation=self._enum_value(getattr(member, "relation", None)) or "viewer",
                source_ref=str(member.id),
                snapshot={
                    "membership_source": member.membership_source or "manual",
                    "member_id": int(member.id),
                },
                status=status,
                last_error=error,
            )

        grants = await self.source_repository.list_active_department_file_grants(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        for grant in grants:
            granted_at = getattr(grant, "granted_at", None)
            await self.repository.upsert_item(
                tenant_id=tenant_id,
                event_id=int(event.id),
                item_key=self.department_file_item_key(grant.space_id, grant.file_id),
                item_type=DepartmentTransferCleanupItemType.DEPARTMENT_FILE_GRANT,
                user_id=user_id,
                resource_type="knowledge_file",
                resource_id=str(grant.file_id),
                root_space_id=int(grant.space_id),
                relation="viewer",
                source_ref=str(grant.id),
                snapshot={
                    "grant_id": int(grant.id),
                    "approval_instance_id": int(grant.approval_instance_id),
                    "granted_at": granted_at.isoformat() if granted_at else None,
                },
            )

        await self.repository.set_snapshot_complete(int(event.id), complete=True, error=None)

    @staticmethod
    def knowledge_item_key(resource_type: str, resource_id: str | int, relation: str) -> str:
        return f"rebac_tuple:{resource_type}:{resource_id}:{relation}"

    @staticmethod
    def department_file_item_key(space_id: int, file_id: int) -> str:
        return f"department_file_grant:{space_id}:{file_id}"

    @staticmethod
    def space_membership_item_key(space_id: str | int) -> str:
        return f"space_membership:{space_id}"

    @staticmethod
    def _is_target_binding(binding: dict, user_id: int) -> bool:
        return (
            binding.get("resource_type") in _KNOWLEDGE_RESOURCE_TYPES
            and binding.get("subject_type") == "user"
            and str(binding.get("subject_id")) == str(user_id)
            and binding.get("relation") in _DIRECT_RELATIONS
        )

    @staticmethod
    def _scope_status(
        *,
        context: dict | None,
        user_id: int,
        resource_type: str,
    ) -> tuple[str, str | None]:
        if context is None:
            return DepartmentTransferCleanupItemStatus.SKIPPED, "resource_scope_unresolved"
        if str(context.get("scope_level")) not in _INCLUDED_SCOPE_LEVELS:
            return DepartmentTransferCleanupItemStatus.SKIPPED, "personal_space_excluded"
        if int(context.get("creator_user_id") or 0) == user_id:
            return DepartmentTransferCleanupItemStatus.SKIPPED, "resource_creator_excluded"
        if (
            resource_type in {"folder", "knowledge_file"}
            and int(context.get("uploader_user_id") or 0) == user_id
        ):
            return DepartmentTransferCleanupItemStatus.SKIPPED, "file_uploader_excluded"
        return DepartmentTransferCleanupItemStatus.PENDING, None

    @staticmethod
    def _enum_value(value) -> str:
        return str(getattr(value, "value", value) or "").lower()

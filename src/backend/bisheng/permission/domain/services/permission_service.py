"""Business-independent permission services.

``F048PermissionService`` is the sole authorization facade for migrated
business resources. ``PermissionService`` remains only as a narrow compatibility
bridge for identity relations and the explicitly allowlisted LLM resources.
It never loads business resources or derives tenant, status, parent, or creator
facts.
"""

from __future__ import annotations

import logging
import re

from bisheng.core.openfga.authorization_model_f048 import LEGACY_RESOURCE_TYPES
from bisheng.core.openfga.exceptions import FGAConnectionError, FGAWriteError
from bisheng.permission.domain.schemas.permission_schema import (
    UNCACHEABLE_RELATIONS,
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
    PermissionLevel,
    ResourcePermissionItem,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services import (
    permission_action_service as f048_permission_action_service,
)

logger = logging.getLogger(__name__)

F048PermissionService = f048_permission_action_service.F048PermissionService
PermissionActor = f048_permission_action_service.PermissionActor


class PermissionService:
    """Identity/LLM compatibility bridge isolated from F048 resources."""

    _IDENTITY_RELATION_TYPES = frozenset(
        {
            "system",
            "tenant",
            "department",
            "user_group",
        }
    )
    _LEGACY_INTERNAL_RESOURCE_TYPES = frozenset(LEGACY_RESOURCE_TYPES)
    _ALLOWED_RUNTIME_TYPES = (
        _IDENTITY_RELATION_TYPES | _LEGACY_INTERNAL_RESOURCE_TYPES
    )
    _FGA_BATCH_SIZE = 100
    _SUBJECT_RE = re.compile(
        r"^(user|department|user_group):(\d+)"
        r"(?:#(member|subtree_member|admin))?$"
    )

    @classmethod
    def _require_allowed_runtime_type(cls, object_type: str) -> str:
        normalized = str(object_type or "").strip().lower()
        if normalized not in cls._ALLOWED_RUNTIME_TYPES:
            raise RuntimeError(
                "Legacy PermissionService cannot authorize an F048 "
                f"business resource: {normalized or '<empty>'}"
            )
        return normalized

    @classmethod
    def _require_allowed_operations(
        cls,
        operations: list[TupleOperation],
    ) -> None:
        for operation in operations:
            object_type, separator, object_id = operation.object.partition(":")
            if not separator or not object_id:
                raise ValueError(
                    f"Invalid OpenFGA object key: {operation.object}"
                )
            cls._require_allowed_runtime_type(object_type)

    @classmethod
    async def check(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        object_id: str,
        login_user=None,
        consistency: str | None = None,
    ) -> bool:
        """Check an identity or allowlisted LLM relation, failing closed."""

        object_type = cls._require_allowed_runtime_type(object_type)
        if login_user and login_user.is_admin():
            return True

        strong_consistency = bool(consistency)
        if relation not in UNCACHEABLE_RELATIONS and not strong_consistency:
            from bisheng.permission.domain.services.permission_cache import (
                PermissionCache,
            )

            cached = await PermissionCache.get_check(
                user_id,
                relation,
                object_type,
                object_id,
            )
            if cached is not None:
                return cached

        try:
            fga = await cls._aget_fga()
            if fga is None:
                return False
            allowed = await fga.check(
                user=f"user:{user_id}",
                relation=relation,
                object=f"{object_type}:{object_id}",
                consistency=consistency,
            )
        except FGAConnectionError as exc:
            logger.error(
                "OpenFGA unavailable during identity/LLM check: %s",
                exc,
            )
            return False
        except Exception as exc:
            logger.error(
                "Identity/LLM permission check failed closed: %s",
                exc,
            )
            return False

        if relation not in UNCACHEABLE_RELATIONS and not strong_consistency:
            from bisheng.permission.domain.services.permission_cache import (
                PermissionCache,
            )

            await PermissionCache.set_check(
                user_id,
                relation,
                object_type,
                object_id,
                allowed,
            )
        return bool(allowed)

    @classmethod
    async def list_accessible_ids(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        login_user=None,
    ) -> list[str] | None:
        """List identity/LLM object IDs without loading business rows."""

        object_type = cls._require_allowed_runtime_type(object_type)
        if login_user and login_user.is_admin():
            return None

        from bisheng.permission.domain.services.permission_cache import (
            PermissionCache,
        )

        if relation not in UNCACHEABLE_RELATIONS:
            cached = await PermissionCache.get_list_objects(
                user_id,
                relation,
                object_type,
            )
            if cached is not None:
                return list(dict.fromkeys(str(value) for value in cached))

        try:
            fga = await cls._aget_fga()
            if fga is None:
                return []
            raw_objects = await fga.list_objects(
                user=f"user:{user_id}",
                relation=relation,
                type=object_type,
            )
        except FGAConnectionError as exc:
            logger.error(
                "OpenFGA unavailable during identity/LLM list: %s",
                exc,
            )
            return []
        except Exception as exc:
            logger.error(
                "Identity/LLM permission list failed closed: %s",
                exc,
            )
            return []

        prefix = f"{object_type}:"
        ids = list(
            dict.fromkeys(
                value.removeprefix(prefix)
                for value in raw_objects
                if value.startswith(prefix) and value.removeprefix(prefix)
            )
        )
        if relation not in UNCACHEABLE_RELATIONS:
            await PermissionCache.set_list_objects(
                user_id,
                relation,
                object_type,
                ids,
            )
        return ids

    @classmethod
    async def authorize(
        cls,
        object_type: str,
        object_id: str,
        grants: list[AuthorizeGrantItem] | None = None,
        revokes: list[AuthorizeRevokeItem] | None = None,
        enforce_fga_success: bool = False,
        recovery_owner: str = "service",
        dispatch_file_change_approver_reconcile: bool = True,
    ) -> None:
        """Write identity/LLM tuples without expanding business membership."""

        object_type = cls._require_allowed_runtime_type(object_type)
        operations: list[TupleOperation] = []
        affected_user_ids: set[int] = set()
        has_userset_subject = False

        for action, items in (
            ("write", grants or []),
            ("delete", revokes or []),
        ):
            for item in items:
                fga_user = cls._subject_userset(
                    item.subject_type,
                    item.subject_id,
                    item.include_children,
                )
                operations.append(
                    TupleOperation(
                        action=action,
                        user=fga_user,
                        relation=item.relation,
                        object=f"{object_type}:{object_id}",
                    )
                )
                if item.subject_type == "user":
                    affected_user_ids.add(int(item.subject_id))
                else:
                    has_userset_subject = True

        if not operations:
            return

        write_keys = {
            (operation.user, operation.relation, operation.object)
            for operation in operations
            if operation.action == "write"
        }
        operations = [
            operation
            for operation in operations
            if not (
                operation.action == "delete"
                and (
                    operation.user,
                    operation.relation,
                    operation.object,
                )
                in write_keys
            )
        ]
        await cls.batch_write_tuples(
            operations,
            raise_on_failure=enforce_fga_success,
            stop_on_failure=enforce_fga_success,
            recovery_owner=recovery_owner,
        )

        if enforce_fga_success and dispatch_file_change_approver_reconcile:
            from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
                dispatch_file_change_approver_reconcile_for_permission_change,
            )

            resource_tenant_id = await cls.resolve_resource_tenant_id(
                object_type,
                object_id,
            )
            # This runs only after the authoritative OpenFGA write succeeds.
            # Strict resolver failures propagate so callers cannot mistake an
            # unavailable approver source for an authoritative empty set.
            await dispatch_file_change_approver_reconcile_for_permission_change(
                resource_type=object_type,
                resource_id=object_id,
                grants=grants or (),
                revokes=revokes or (),
                tenant_id=resource_tenant_id,
            )

        # Invalidate cache for directly affected users
        if affected_user_ids:
            from bisheng.permission.domain.services.permission_cache import PermissionCache
        from bisheng.permission.domain.services.permission_cache import (
            PermissionCache,
        )

        if has_userset_subject:
            await PermissionCache.invalidate_all()
        else:
            for user_id in affected_user_ids:
                await PermissionCache.invalidate_user(user_id)

    @staticmethod
    def _subject_userset(
        subject_type: str,
        subject_id: int,
        include_children: bool,
    ) -> str:
        if subject_type == "user":
            return f"user:{subject_id}"
        if subject_type == "department":
            relation = "subtree_member" if include_children else "member"
            return f"department:{subject_id}#{relation}"
        if subject_type == "user_group":
            return f"user_group:{subject_id}#member"
        raise ValueError(f"Unsupported permission subject: {subject_type}")

    @classmethod
    async def batch_write_tuples(
        cls,
        operations: list[TupleOperation],
        crash_safe: bool = False,
        raise_on_failure: bool = False,
        stop_on_failure: bool = False,
        recovery_owner: str = "service",
    ) -> None:
        """Write identity/LLM tuples with legacy FailedTuple compensation.

        Chunks into batches of _FGA_BATCH_SIZE to respect OpenFGA's per-request limit.
        Used by ChangeHandler.execute_async(). Failures recorded in FailedTuple.

        Args:
            operations: List of tuple operations to execute.
            crash_safe: If True, pre-insert FailedTuple records before the FGA call
                so a process crash between MySQL commit and FGA write leaves
                recoverable records. On FGA success, the pre-inserted records are
                deleted. Used by ChangeHandler callsites where the DB transaction
                has already committed.
        """
        if recovery_owner not in {"service", "caller"}:
            raise ValueError("recovery_owner must be 'service' or 'caller'")
        if recovery_owner == "caller" and crash_safe:
            raise ValueError("caller-owned recovery cannot use crash_safe FailedTuple records")
        if not operations:
            return
        operations = cls._dedupe_operations(operations)
        cls._require_allowed_operations(operations)

        pre_recorded_ids: list[int] = []
        saved_failure_ops = False
        if crash_safe:
            pre_recorded_ids = await cls._pre_record_failed_tuples(operations)

        try:
            fga = await cls._aget_fga()
            if fga is None:
                if not crash_safe and recovery_owner == "service":
                    await cls._save_failed_tuples(operations, "FGAClient not available")
                if raise_on_failure:
                    raise FGAConnectionError("FGAClient not available")
                return

            failed_ops: list[TupleOperation] = []
            for offset in range(0, len(operations), cls._FGA_BATCH_SIZE):
                chunk = operations[offset : offset + cls._FGA_BATCH_SIZE]
                writes = [
                    {
                        "user": operation.user,
                        "relation": operation.relation,
                        "object": operation.object,
                    }
                    for operation in chunk
                    if operation.action == "write"
                ]
                deletes = [
                    {
                        "user": operation.user,
                        "relation": operation.relation,
                        "object": operation.object,
                    }
                    for operation in chunk
                    if operation.action == "delete"
                ]
                try:
                    await fga.write_tuples(
                        writes=writes or None,
                        deletes=deletes or None,
                    )
                except FGAWriteError as exc:
                    logger.info(
                        "Identity tuple batch fell back to single writes for "
                        "%d operations: %s",
                        len(chunk),
                        exc,
                    )
                    failed_ops.extend(
                        await cls._write_operations_individually(
                            fga,
                            chunk,
                            stop_on_failure=stop_on_failure,
                        )
                    )

            if failed_ops:
                logger.error(
                    "OpenFGA tuple write left %d unresolved operations (raise_on_failure=%s, crash_safe=%s)",
                    len(failed_ops),
                    raise_on_failure,
                    crash_safe,
                )
                if not crash_safe and recovery_owner == "service":
                    await cls._save_failed_tuples(
                        failed_ops,
                        "OpenFGA single-tuple fallback failed",
                    )
                    saved_failure_ops = True
                if raise_on_failure:
                    raise FGAWriteError(
                        "OpenFGA write did not complete successfully; "
                        f"{len(failed_ops)} tuple operations failed"
                    )
                return

            if pre_recorded_ids:
                await cls._delete_pre_recorded(pre_recorded_ids)

        except Exception as e:
            logger.error("Failed to batch write tuples: %s", e)
            if not crash_safe and not saved_failure_ops and recovery_owner == "service":
                await cls._save_failed_tuples(operations, str(e))
            # If crash_safe, pre-recorded entries remain as 'pending' for retry
            if raise_on_failure:
                raise

    @classmethod
    async def _write_operations_individually(
        cls,
        fga,
        operations: list[TupleOperation],
        stop_on_failure: bool = False,
    ) -> list[TupleOperation]:
        failed: list[TupleOperation] = []
        for index, operation in enumerate(operations):
            payload = {
                "user": operation.user,
                "relation": operation.relation,
                "object": operation.object,
            }
            try:
                if operation.action == "write":
                    await fga.write_tuples(writes=[payload])
                else:
                    await fga.write_tuples(deletes=[payload])
            except FGAWriteError as exc:
                if cls._is_idempotent_tuple_error(
                    operation.action,
                    str(exc),
                ):
                    continue
                failed.append(operation)
                if stop_on_failure:
                    failed.extend(operations[index + 1 :])
                    break
            except FGAConnectionError:
                raise
            except Exception:
                failed.append(operation)
                if stop_on_failure:
                    failed.extend(operations[index + 1 :])
                    break
        return failed

    @staticmethod
    def _is_idempotent_tuple_error(
        action: str,
        error_msg: str,
    ) -> bool:
        text = error_msg.lower()
        if action == "write":
            return (
                "already exists" in text
                or "cannot write a tuple which already exists" in text
            )
        if action == "delete":
            return (
                "does not exist" in text
                or "did not exist" in text
                or "tuple to be deleted did not exist" in text
            )
        return False

    @staticmethod
    def _dedupe_operations(
        operations: list[TupleOperation],
    ) -> list[TupleOperation]:
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[TupleOperation] = []
        for operation in operations:
            key = (
                operation.action,
                operation.user,
                operation.relation,
                operation.object,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(operation)
        return deduped

    @classmethod
    async def get_resource_permissions(
        cls,
        object_type: str,
        object_id: str,
    ) -> list[ResourcePermissionItem]:
        """Return raw legacy roster identities without business display data."""

        object_type = cls._require_allowed_runtime_type(object_type)
        try:
            fga = await cls._aget_fga()
            if fga is None:
                return []
            tuples = await fga.read_tuples(
                object=f"{object_type}:{object_id}"
            )
        except Exception as exc:
            logger.error("Failed to read identity/LLM roster: %s", exc)
            return []

        items: list[ResourcePermissionItem] = []
        seen: set[tuple[str, int, str, bool]] = set()
        for row in tuples:
            match = cls._SUBJECT_RE.match(str(row.get("user", "")))
            if match is None:
                continue
            subject_type, subject_id, userset_relation = match.groups()
            include_children = userset_relation == "subtree_member"
            key = (
                subject_type,
                int(subject_id),
                str(row.get("relation", "")),
                include_children,
            )
            if key in seen:
                continue
            seen.add(key)
            items.append(
                ResourcePermissionItem(
                    subject_type=subject_type,
                    subject_id=int(subject_id),
                    relation=key[2],
                    include_children=(
                        include_children
                        if subject_type == "department"
                        else None
                    ),
                )
            )
        return items

    @classmethod
    async def get_permission_level(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
        login_user=None,
    ) -> str | None:
        """Return the highest explicit level for an allowlisted LLM resource."""

        object_type = cls._require_allowed_runtime_type(object_type)
        if login_user and login_user.is_admin():
            return PermissionLevel.owner.value
        try:
            fga = await cls._aget_fga()
            if fga is None:
                return None
            levels = tuple(PermissionLevel)
            results = await fga.batch_check(
                [
                    {
                        "user": f"user:{user_id}",
                        "relation": level.value,
                        "object": f"{object_type}:{object_id}",
                    }
                    for level in levels
                ]
            )
            for level, allowed in zip(levels, results, strict=True):
                if allowed:
                    return level.value
        except Exception as exc:
            logger.error(
                "Failed to resolve identity/LLM permission level: %s",
                exc,
            )
        return None

    @classmethod
    async def get_implicit_permission_level(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
        login_user=None,
    ) -> str | None:
        """Compatibility surface with no creator or business-data fallback."""

        del user_id, object_id
        cls._require_allowed_runtime_type(object_type)
        is_admin = getattr(login_user, "is_admin", None)
        if callable(is_admin) and is_admin():
            return PermissionLevel.owner.value
        return None

    @classmethod
    async def _save_failed_tuples(
        cls,
        operations: list[TupleOperation],
        error_msg: str,
    ) -> None:
        if not operations:
            return
        try:
            from bisheng.database.models.failed_tuple import (
                FailedTuple,
                FailedTupleDao,
            )

            tuples = [
                FailedTuple(
                    action=operation.action,
                    fga_user=operation.user,
                    relation=operation.relation,
                    object=operation.object,
                    error_message=error_msg,
                )
                for operation in operations
            ]
            await FailedTupleDao.acreate_batch(tuples)
        except Exception as exc:
            logger.critical(
                "Failed to record identity tuple compensation: %s",
                exc,
            )

    @classmethod
    async def _pre_record_failed_tuples(
        cls,
        operations: list[TupleOperation],
    ) -> list[int]:
        try:
            from bisheng.database.models.failed_tuple import (
                FailedTuple,
                FailedTupleDao,
            )

            tuples = [
                FailedTuple(
                    action=operation.action,
                    fga_user=operation.user,
                    relation=operation.relation,
                    object=operation.object,
                    error_message="pre-recorded for crash safety",
                )
                for operation in operations
            ]
            await FailedTupleDao.acreate_batch(tuples)
            return [int(row.id) for row in tuples if row.id is not None]
        except Exception as exc:
            logger.warning(
                "Failed to pre-record identity tuple compensation: %s",
                exc,
            )
            return []

    @classmethod
    async def _delete_pre_recorded(
        cls,
        record_ids: list[int],
    ) -> None:
        if not record_ids:
            return
        try:
            from bisheng.database.models.failed_tuple import FailedTupleDao

            for record_id in record_ids:
                await FailedTupleDao.aupdate_succeeded(record_id)
        except Exception as exc:
            logger.debug(
                "Failed to complete identity tuple compensation: %s",
                exc,
            )

    @staticmethod
    def _get_fga():
        from bisheng.core.openfga.manager import get_fga_client

        return get_fga_client()

    @classmethod
    async def _aget_fga(cls):
        from bisheng.core.openfga.manager import aget_fga_client

        fga = await aget_fga_client()
        return fga if fga is not None else cls._get_fga()

    @classmethod
    async def resolve_resource_relation_user_ids_strict(
        cls,
        *,
        tenant_id: int,
        object_type: str,
        object_id: str,
        relations: tuple[str, ...],
    ) -> set[int]:
        """Resolve relation subjects to concrete users without outage fallback.

        Unlike :meth:`get_resource_permissions`, this authorization-boundary API
        never converts OpenFGA or subject-expansion failures into an empty result.
        Callers may therefore treat an empty set as an authoritative answer.
        Department grants are already expanded to one tuple per included
        department when written, so each ``department:id#member`` tuple expands
        only that exact department here.
        """
        from bisheng.core.context.tenant import get_current_tenant_id

        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for strict permission resolution")
        if not object_type or not object_id:
            raise ValueError("object_type and object_id are required")

        normalized_relations = tuple(dict.fromkeys(str(relation) for relation in relations if relation))
        if not normalized_relations:
            raise ValueError("at least one relation is required")

        fga = await cls._aget_fga()
        if fga is None:
            raise FGAConnectionError("OpenFGA client is unavailable")

        from bisheng.permission.domain.repositories.grant_subject_query_repository import (
            GrantSubjectQueryRepository,
        )

        object_ref = f"{object_type}:{object_id}"
        subject_repository = GrantSubjectQueryRepository()
        direct_user_ids: set[int] = set()
        department_ids: set[int] = set()
        group_member_ids: set[int] = set()
        group_admin_ids: set[int] = set()
        for relation in normalized_relations:
            tuples = await fga.read_tuples(
                object=object_ref,
                relation=relation,
                consistency="HIGHER_CONSISTENCY",
            )
            for item in tuples or []:
                if item.get("object") != object_ref or item.get("relation") != relation:
                    raise ValueError("OpenFGA returned a tuple outside the requested relation scope")

                raw_subject = item.get("user", "")
                match = cls._SUBJECT_RE.fullmatch(raw_subject)
                if match is None:
                    raise ValueError(f"Unsupported OpenFGA subject: {raw_subject!r}")
                subject_type, subject_id_text, member_suffix = match.groups()
                if (
                    (subject_type == "user" and member_suffix is not None)
                    or (subject_type == "department" and member_suffix != "#member")
                    or (subject_type == "user_group" and member_suffix not in {"#member", "#admin"})
                ):
                    raise ValueError(f"Unsupported OpenFGA subject: {raw_subject!r}")

                subject_id = int(subject_id_text)
                if subject_type == "user":
                    direct_user_ids.add(subject_id)
                elif subject_type == "department":
                    department_ids.add(subject_id)
                elif member_suffix == "#admin":
                    group_admin_ids.add(subject_id)
                else:
                    group_member_ids.add(subject_id)

        department_members = (
            await subject_repository.resolve_exact_department_member_user_ids_batch(
                department_ids=department_ids,
                tenant_id=int(tenant_id),
            )
            if department_ids
            else {}
        )
        invalid_department_ids = department_ids.difference(department_members)
        if invalid_department_ids:
            raise ValueError(
                f"OpenFGA department subjects are outside tenant {tenant_id}: {sorted(invalid_department_ids)}"
            )

        group_members = (
            await subject_repository.resolve_user_group_member_user_ids_batch(
                group_ids=group_member_ids,
                tenant_id=int(tenant_id),
            )
            if group_member_ids
            else {}
        )
        invalid_group_ids = group_member_ids.difference(group_members)
        if invalid_group_ids:
            raise ValueError(f"OpenFGA user-group subjects are outside tenant {tenant_id}: {sorted(invalid_group_ids)}")

        group_admins = (
            await subject_repository.resolve_user_group_admin_user_ids_batch(
                group_ids=group_admin_ids,
                tenant_id=int(tenant_id),
            )
            if group_admin_ids
            else {}
        )
        invalid_admin_group_ids = group_admin_ids.difference(group_admins)
        if invalid_admin_group_ids:
            raise ValueError(
                f"OpenFGA user-group subjects are outside tenant {tenant_id}: {sorted(invalid_admin_group_ids)}"
            )

        user_ids = direct_user_ids.union(
            *(member_ids for member_ids in department_members.values()),
            *(member_ids for member_ids in group_members.values()),
            *(member_ids for member_ids in group_admins.values()),
        )
        if not user_ids:
            return set()
        return await subject_repository.filter_active_user_ids_in_tenant(
            user_ids=user_ids,
            tenant_id=int(tenant_id),
        )

    @classmethod
    async def resolve_permanent_creator_user_ids_strict(
        cls,
        *,
        tenant_id: int,
        object_type: str,
        object_id: str,
    ) -> set[int]:
        """Resolve active creators whose resource type defines permanent ownership.

        The OpenFGA availability boundary remains the caller's responsibility;
        this method only projects the established knowledge-space creator rule
        after the caller has completed its strict relation read.
        """
        from bisheng.core.context.tenant import get_current_tenant_id

        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for permanent creator resolution")
        if object_type != "knowledge_space":
            return set()

        creator_id = await cls._get_resource_creator(object_type, object_id)
        if creator_id is None:
            return set()

        from bisheng.permission.domain.repositories.grant_subject_query_repository import (
            GrantSubjectQueryRepository,
        )

        return await GrantSubjectQueryRepository().filter_active_user_ids_in_tenant(
            user_ids={int(creator_id)},
            tenant_id=int(tenant_id),
        )

    @classmethod
    async def get_resource_permissions_from_bindings(
        cls,
        bindings: list[dict],
        model_map: dict[str, dict],
    ) -> list[ResourcePermissionItem]:
        """Build the permission-management list from persisted UI bindings.

        This is intentionally a display-only read path. It does not query
        OpenFGA and must never be used for permission decisions. Callers remain
        responsible for access checks through the normal permission service.
        """
        tuple_rows: list[dict] = []
        binding_map: dict[tuple[str, int, str], dict] = {}
        seen: set[tuple[str, int, str]] = set()

        for binding in bindings:
            subject_type = binding.get("subject_type")
            relation = binding.get("relation")
            if subject_type not in {"user", "department", "user_group"}:
                continue
            if relation not in {"owner", "manager", "editor", "viewer"}:
                continue
            try:
                subject_id = int(binding.get("subject_id"))
            except (TypeError, ValueError):
                continue

            key = (subject_type, subject_id, relation)
            binding_map[key] = binding
            if key in seen:
                continue
            seen.add(key)
            member_suffix = "" if subject_type == "user" else "#member"
            tuple_rows.append(
                {
                    "user": f"{subject_type}:{subject_id}{member_suffix}",
                    "relation": relation,
                }
            )

        permissions = await cls._enrich_permission_tuples(tuple_rows)
        for item in permissions:
            binding = binding_map.get((item.subject_type, int(item.subject_id), item.relation))
            if binding is None:
                continue
            item.include_children = binding.get("include_children")
            item.model_id = binding.get("model_id")
            item.model_name = model_map.get(item.model_id, {}).get("name")
        return permissions

    @classmethod
    async def resolve_resource_tenant_id(cls, object_type: str, object_id: str) -> int | None:
        """Public owner API for the authoritative resource tenant id."""

        tenant_id = await cls._resolve_resource_tenant(object_type, object_id)
        if tenant_id is None or isinstance(tenant_id, bool) or int(tenant_id) <= 0:
            return None
        return int(tenant_id)

    @classmethod
    async def _resolve_resource_tenant(cls, object_type: str, object_id: str):
        """Resolve a resource's owning tenant_id, or None to skip tenant gating.

        F013 only enforces tenant gating for primary resource types that carry
        an owning tenant_id we can look up cheaply (workflow, assistant,
        knowledge_space / knowledge_library). Other types (folder,
        knowledge_file, channel, tool,
        dashboard, llm_*) inherit visibility via their parent or are not yet
        wired to multi-tenant; for those, returning None falls through to the
        existing FGA chain which still honors tenant#shared_to#member at the
        DSL level. Any DAO error degrades to None for safety (legacy paths).
        """
        try:
            from bisheng.core.context.tenant import bypass_tenant_filter

            with bypass_tenant_filter():
                if object_type == "workflow":
                    from bisheng.database.models.flow import FlowDao

                    obj = await FlowDao.aget_flow_by_id(str(object_id))
                    return obj.tenant_id if obj else None
                if object_type == "assistant":
                    from bisheng.database.models.assistant import AssistantDao

                    obj = await AssistantDao.aget_one_assistant(str(object_id))
                    return obj.tenant_id if obj else None
                if object_type == "knowledge_space":
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

                    obj = await KnowledgeDao.aquery_by_id(int(object_id))
                    return obj.tenant_id if obj and obj.type == KnowledgeTypeEnum.SPACE.value else None
                if object_type == "knowledge_library":
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

                    obj = await KnowledgeDao.aquery_by_id(int(object_id))
                    if obj and obj.type in (KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value):
                        return obj.tenant_id
                    return None
        except Exception as e:
            logger.warning(
                "_resolve_resource_tenant failed for %s:%s: %s",
                object_type,
                object_id,
                e,
            )
            return None
        return None

    @classmethod
    async def _is_shared_to(
        cls,
        user_id: int,
        target_tenant_id: int,
        visible_tenant_ids: list[int] | None = None,
    ) -> bool:
        """True iff any visible tenant of the user has ``shared_to`` on target tenant.

        F017 writes tuples as ``tenant:{child}#shared_to -> tenant:{root}``.
        OpenFGA ``object`` must stay in ``type:id`` form, so we must query
        against ``object=tenant:{target}`` and use the visible tenant itself
        as the tuple subject.
        """
        fga = await cls._aget_fga()
        if fga is None:
            return False

        candidate_tenant_ids = [int(one) for one in (visible_tenant_ids or []) if str(one).isdigit()]
        if not candidate_tenant_ids:
            try:
                from bisheng.database.models.tenant import ROOT_TENANT_ID, UserTenantDao

                active = await UserTenantDao.aget_active_user_tenant(user_id)
                if active and active.tenant_id != ROOT_TENANT_ID:
                    candidate_tenant_ids = [int(active.tenant_id), ROOT_TENANT_ID]
                else:
                    candidate_tenant_ids = [ROOT_TENANT_ID]
            except Exception as e:
                logger.warning(
                    "[FGA shared_to check] fallback visible tenant lookup failed "
                    "user_id=%s target_tenant_id=%s error=%s",
                    user_id,
                    target_tenant_id,
                    e,
                )
                return False

        fga_relation = "shared_to"
        fga_object = f"tenant:{target_tenant_id}"
        try:
            for tenant_id in candidate_tenant_ids:
                fga_user = f"tenant:{tenant_id}"
                logger.info(
                    "[FGA shared_to check] user_id=%s target_tenant_id=%s "
                    "candidate_tenant_id=%s user=%s relation=%s object=%s",
                    user_id,
                    target_tenant_id,
                    tenant_id,
                    fga_user,
                    fga_relation,
                    fga_object,
                )
                if await fga.check(
                    user=fga_user,
                    relation=fga_relation,
                    object=fga_object,
                ):
                    return True
            return False
        except FGAConnectionError:
            return False
        except Exception as e:
            logger.error(
                "[FGA shared_to check] failed user_id=%s target_tenant_id=%s "
                "candidate_tenant_ids=%s relation=%s object=%s error=%s",
                user_id,
                target_tenant_id,
                candidate_tenant_ids,
                fga_relation,
                fga_object,
                e,
            )
            return False

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
    _ALLOWED_RUNTIME_TYPES = _IDENTITY_RELATION_TYPES | _LEGACY_INTERNAL_RESOURCE_TYPES
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
                f"Legacy PermissionService cannot authorize an F048 business resource: {normalized or '<empty>'}"
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
                raise ValueError(f"Invalid OpenFGA object key: {operation.object}")
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
        )

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
        if subject_type == "service_account":
            if include_children:
                raise ValueError("service accounts do not support include_children")
            return f"service_account:{subject_id}"
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
    ) -> None:
        """Write identity/LLM tuples with legacy FailedTuple compensation."""

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
                if not crash_safe:
                    await cls._save_failed_tuples(
                        operations,
                        "FGAClient not available",
                    )
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
                        "Identity tuple batch fell back to single writes for %d operations: %s",
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
                if not crash_safe:
                    await cls._save_failed_tuples(
                        failed_ops,
                        "OpenFGA single-tuple fallback failed",
                    )
                    saved_failure_ops = True
                if raise_on_failure:
                    raise FGAWriteError(
                        f"OpenFGA write did not complete successfully; {len(failed_ops)} tuple operations failed"
                    )
                return

            if pre_recorded_ids:
                await cls._delete_pre_recorded(pre_recorded_ids)
        except Exception as exc:
            logger.error("Failed to batch write identity tuples: %s", exc)
            if not crash_safe and not saved_failure_ops:
                await cls._save_failed_tuples(operations, str(exc))
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
            return "already exists" in text or "cannot write a tuple which already exists" in text
        if action == "delete":
            return "does not exist" in text or "did not exist" in text or "tuple to be deleted did not exist" in text
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
            tuples = await fga.read_tuples(object=f"{object_type}:{object_id}")
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
                    include_children=(include_children if subject_type == "department" else None),
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

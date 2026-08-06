"""Application protocols for identity and platform permission relations.

Business modules use these semantic values and never receive an OpenFGA
client or encode OpenFGA tuple dictionaries themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.core.openfga.client import FGAClient

_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RELATION_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_token(value: object, *, kind: str, pattern: re.Pattern[str]) -> str:
    normalized = str(value or "").strip()
    if not pattern.fullmatch(normalized):
        raise ValueError(f"Invalid permission {kind}: {normalized!r}")
    return normalized


def _require_id(value: object, *, kind: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or any(separator in normalized for separator in (":", "#")):
        raise ValueError(f"Invalid permission {kind}: {normalized!r}")
    return normalized


@dataclass(frozen=True, slots=True)
class PermissionSubject:
    subject_type: str
    subject_id: str
    relation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "subject_type", _require_token(self.subject_type, kind="subject type", pattern=_TYPE_RE)
        )
        object.__setattr__(self, "subject_id", _require_id(self.subject_id, kind="subject id"))
        if self.relation is not None:
            object.__setattr__(
                self, "relation", _require_token(self.relation, kind="subject relation", pattern=_RELATION_RE)
            )

    def _backend_key(self) -> str:
        value = f"{self.subject_type}:{self.subject_id}"
        return f"{value}#{self.relation}" if self.relation else value


@dataclass(frozen=True, slots=True)
class PermissionObject:
    resource_type: str
    resource_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_type", _require_token(self.resource_type, kind="resource type", pattern=_TYPE_RE)
        )
        object.__setattr__(self, "resource_id", _require_id(self.resource_id, kind="resource id"))

    def _backend_key(self) -> str:
        return f"{self.resource_type}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class PermissionRelation:
    subject: PermissionSubject
    relation: str
    resource: PermissionObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "relation", _require_token(self.relation, kind="relation", pattern=_RELATION_RE))


@dataclass(frozen=True, slots=True)
class PermissionRelationChange:
    """One grant or revoke requested through the permission application."""

    action: Literal["grant", "revoke"]
    relation: PermissionRelation

    def __post_init__(self) -> None:
        if self.action not in ("grant", "revoke"):
            raise ValueError(f"Invalid permission change action: {self.action!r}")


class PermissionRelationQueryPort(Protocol):
    async def check(
        self,
        *,
        subject: PermissionSubject,
        relation: str,
        resource: PermissionObject,
        consistency: str | None = None,
    ) -> bool: ...

    async def batch_check(
        self,
        checks: tuple[PermissionRelation, ...],
        *,
        consistency: str | None = None,
    ) -> tuple[bool, ...]: ...

    async def list_resource_ids(
        self,
        *,
        subject: PermissionSubject,
        relation: str,
        resource_type: str,
    ) -> tuple[str, ...]: ...

    async def list_subject_ids(
        self,
        *,
        resource: PermissionObject,
        relation: str,
        subject_type: str,
    ) -> tuple[str, ...]: ...

    async def list_relations(
        self,
        *,
        resource: PermissionObject | None = None,
        subject: PermissionSubject | None = None,
        relation: str | None = None,
    ) -> tuple[PermissionRelation, ...]: ...


class PermissionRelationMutationPort(Protocol):
    async def grant(self, relations: tuple[PermissionRelation, ...]) -> None: ...

    async def revoke(self, relations: tuple[PermissionRelation, ...]) -> None: ...

    async def apply(
        self,
        *,
        grants: tuple[PermissionRelation, ...] = (),
        revokes: tuple[PermissionRelation, ...] = (),
    ) -> None: ...

    async def apply_changes(
        self,
        changes: tuple[PermissionRelationChange, ...],
        *,
        crash_safe: bool = False,
    ) -> None: ...


class PermissionRelationPort(PermissionRelationQueryPort, PermissionRelationMutationPort, Protocol):
    """Complete application boundary for platform permission relations."""


class PermissionRelationApplication(PermissionRelationPort):
    """Translate application permission relations to the infrastructure client."""

    def __init__(self, client: FGAClient) -> None:
        self._client = client

    async def check(
        self,
        *,
        subject: PermissionSubject,
        relation: str,
        resource: PermissionObject,
        consistency: str | None = None,
    ) -> bool:
        relation = _require_token(relation, kind="relation", pattern=_RELATION_RE)
        try:
            return await self._client.check(
                user=subject._backend_key(),
                relation=relation,
                object=resource._backend_key(),
                consistency=consistency,
            )
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc

    async def batch_check(
        self,
        checks: tuple[PermissionRelation, ...],
        *,
        consistency: str | None = None,
    ) -> tuple[bool, ...]:
        if not checks:
            return ()
        try:
            allowed = await self._client.batch_check(
                [self._encoded(relation) for relation in checks],
                consistency=consistency,
            )
            if len(allowed) != len(checks):
                raise RuntimeError("Permission backend returned an incomplete batch result")
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc
        return tuple(bool(value) for value in allowed)

    async def list_resource_ids(
        self,
        *,
        subject: PermissionSubject,
        relation: str,
        resource_type: str,
    ) -> tuple[str, ...]:
        relation = _require_token(relation, kind="relation", pattern=_RELATION_RE)
        resource_type = _require_token(resource_type, kind="resource type", pattern=_TYPE_RE)
        try:
            objects = await self._client.list_objects(
                user=subject._backend_key(),
                relation=relation,
                type=resource_type,
            )
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc
        prefix = f"{resource_type}:"
        return tuple(
            dict.fromkeys(
                value.removeprefix(prefix)
                for value in objects
                if value.startswith(prefix) and value.removeprefix(prefix)
            )
        )

    async def list_subject_ids(
        self,
        *,
        resource: PermissionObject,
        relation: str,
        subject_type: str,
    ) -> tuple[str, ...]:
        relation = _require_token(relation, kind="relation", pattern=_RELATION_RE)
        subject_type = _require_token(subject_type, kind="subject type", pattern=_TYPE_RE)
        try:
            rows = await self._client.read_tuples(
                relation=relation,
                object=resource._backend_key(),
            )
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc
        prefix = f"{subject_type}:"
        return tuple(
            dict.fromkeys(
                value.removeprefix(prefix)
                for row in rows
                if (value := str(row.get("user") or "")).startswith(prefix)
                and "#" not in value
                and value.removeprefix(prefix)
            )
        )

    async def list_relations(
        self,
        *,
        resource: PermissionObject | None = None,
        subject: PermissionSubject | None = None,
        relation: str | None = None,
    ) -> tuple[PermissionRelation, ...]:
        if resource is None and subject is None:
            raise ValueError("Permission relation query requires a resource or subject")
        normalized_relation = (
            _require_token(relation, kind="relation", pattern=_RELATION_RE) if relation is not None else None
        )
        try:
            rows = await self._client.read_tuples(
                user=subject._backend_key() if subject else None,
                relation=normalized_relation,
                object=resource._backend_key() if resource else None,
            )
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc
        parsed: list[PermissionRelation] = []
        for row in rows:
            parsed_relation = self._parse(row)
            if parsed_relation is not None:
                parsed.append(parsed_relation)
        return tuple(parsed)

    async def grant(self, relations: tuple[PermissionRelation, ...]) -> None:
        await self.apply(grants=relations)

    async def revoke(self, relations: tuple[PermissionRelation, ...]) -> None:
        await self.apply(revokes=relations)

    async def apply(
        self,
        *,
        grants: tuple[PermissionRelation, ...] = (),
        revokes: tuple[PermissionRelation, ...] = (),
    ) -> None:
        if not grants and not revokes:
            return
        try:
            await self._client.write_tuples(
                writes=[self._encoded(value) for value in grants] or None,
                deletes=[self._encoded(value) for value in revokes] or None,
            )
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc

    async def apply_changes(
        self,
        changes: tuple[PermissionRelationChange, ...],
        *,
        crash_safe: bool = False,
    ) -> None:
        if not changes:
            return
        if not crash_safe:
            await self.apply(
                grants=tuple(change.relation for change in changes if change.action == "grant"),
                revokes=tuple(change.relation for change in changes if change.action == "revoke"),
            )
            return

        # The durable compatibility queue still stores its historical encoded
        # shape. Keep that translation inside the permission module.
        from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
        from bisheng.permission.domain.services.permission_service import PermissionService

        operations = [
            TupleOperation(
                action="write" if change.action == "grant" else "delete",
                **self._encoded(change.relation),
            )
            for change in changes
        ]
        try:
            await PermissionService.batch_write_tuples(operations, crash_safe=True)
        except Exception as exc:
            raise PermissionServiceUnavailableError(exception=exc) from exc

    @staticmethod
    def _encoded(value: PermissionRelation) -> dict[str, str]:
        return {
            "user": value.subject._backend_key(),
            "relation": value.relation,
            "object": value.resource._backend_key(),
        }

    @staticmethod
    def _parse(value: dict) -> PermissionRelation | None:
        user = str(value.get("user") or "")
        relation = str(value.get("relation") or "")
        resource = str(value.get("object") or "")
        subject_value, subject_separator, subject_relation = user.partition("#")
        subject_type, subject_type_separator, subject_id = subject_value.partition(":")
        resource_type, resource_separator, resource_id = resource.partition(":")
        if not subject_type_separator or not resource_separator:
            return None
        try:
            return PermissionRelation(
                subject=PermissionSubject(
                    subject_type=subject_type,
                    subject_id=subject_id,
                    relation=subject_relation if subject_separator else None,
                ),
                relation=relation,
                resource=PermissionObject(resource_type=resource_type, resource_id=resource_id),
            )
        except ValueError:
            return None


async def is_tenant_admin(user_id: int, tenant_id: int) -> bool:
    """Query the platform permission model for direct tenant administration."""

    permissions = await get_permission_relation_api()
    return await permissions.check(
        subject=PermissionSubject("user", str(user_id)),
        relation="admin",
        resource=PermissionObject("tenant", str(tenant_id)),
    )


async def get_permission_relation_api() -> PermissionRelationPort:
    """Return the relation application only after the permission Context is READY."""

    from bisheng.permission.application.process_runtime import get_f048_process_runtime

    try:
        runtime = await get_f048_process_runtime()
    except PermissionServiceUnavailableError:
        raise
    except Exception as exc:
        raise PermissionServiceUnavailableError(exception=exc) from exc
    components = getattr(runtime, "components", runtime)
    relations = getattr(components, "relations", None)
    if relations is None:
        raise PermissionServiceUnavailableError(msg="Permission relation application is unavailable")
    return relations


def _permission_relation_from_legacy_tuple(
    *,
    user: str,
    relation: str,
    object_key: str,
) -> PermissionRelation:
    """Decode one persisted legacy tuple without exposing client APIs."""

    parsed = PermissionRelationApplication._parse(
        {
            "user": user,
            "relation": relation,
            "object": object_key,
        }
    )
    if parsed is None:
        raise ValueError("Invalid persisted permission relation")
    return parsed

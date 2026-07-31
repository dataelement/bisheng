"""Pure source identity and OpenFGA-delta compiler for F048 Grants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from bisheng.common.errcode.permission import (
    PermissionModelStateConflictError,
    PermissionVersionConflictError,
)
from bisheng.permission.domain.services.projection_service import (
    ProjectionTupleDelta,
)

SOURCE_TYPES = frozenset(
    {
        "DIRECT",
        "DEPARTMENT",
        "USER_GROUP",
        "CREATOR",
        "SPACE_MEMBERSHIP",
        "CHANNEL_MEMBERSHIP",
        "SNAPSHOT_FROM_PARENT",
        "OTHER",
    }
)


@dataclass(frozen=True, slots=True)
class GrantModelSnapshot:
    model_key: str
    active: bool
    action_codes: tuple[str, ...]
    derived_level: int | None = None
    allow_same_level: bool = False


@dataclass(frozen=True, slots=True)
class GrantSourceRecord:
    source_id: int
    subject_type: str
    subject_id: str
    userset_relation: str | None
    include_children: bool
    source_type: str
    source_ref: str
    source_locator: str
    source_fingerprint: str
    projected_subject: str
    protected: bool
    active: bool = True
    version: int = 1


@dataclass(frozen=True, slots=True)
class GrantSnapshot:
    grant_id: str
    tenant_id: int
    resource_type: str
    resource_id: str
    model: GrantModelSnapshot
    active: bool
    sources: tuple[GrantSourceRecord, ...]
    version: int = 1


@dataclass(frozen=True, slots=True)
class GrantSourceMutation:
    grant: GrantSnapshot
    deltas: tuple[ProjectionTupleDelta, ...]
    idempotent: bool = False


@dataclass(frozen=True, slots=True)
class GrantSourceMoveMutation:
    source_grant: GrantSnapshot
    target_grant: GrantSnapshot
    deltas: tuple[ProjectionTupleDelta, ...]


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _source_signature(source: GrantSourceRecord) -> tuple[object, ...]:
    return (
        source.subject_type,
        source.subject_id,
        source.userset_relation,
        source.include_children,
        source.source_type,
        source.source_ref,
        source.source_locator,
        source.projected_subject,
        source.protected,
    )


class GrantSourceService:
    """Maintain source rows without expanding usersets or flattening provenance."""

    def canonicalize_source(
        self,
        *,
        source_id: int,
        subject_type: str,
        subject_id: str,
        source_type: str,
        userset_relation: str | None = None,
        include_children: bool = False,
        source_ref: str | None = None,
        protected: bool = False,
    ) -> GrantSourceRecord:
        if source_id <= 0:
            raise ValueError("source_id must be positive")
        normalized_subject_type = subject_type.strip().lower()
        normalized_subject_id = subject_id.strip()
        normalized_source_type = source_type.strip().upper()
        if not normalized_subject_id:
            raise ValueError("subject_id must not be empty")
        if normalized_source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {source_type}")

        relation: str | None
        projected_subject: str
        if normalized_subject_type == "user":
            if userset_relation is not None or include_children:
                raise ValueError("direct user sources cannot use userset options")
            relation = None
            projected_subject = f"user:{normalized_subject_id}"
        elif normalized_subject_type == "department":
            expected_relation = "subtree_member" if include_children else "member"
            if userset_relation not in {None, expected_relation}:
                raise ValueError("department userset relation is inconsistent")
            relation = expected_relation
            projected_subject = f"department:{normalized_subject_id}#{expected_relation}"
        elif normalized_subject_type == "user_group":
            if include_children:
                raise ValueError("user groups do not support include_children")
            relation = userset_relation or "member"
            if relation not in {"member", "admin"}:
                raise ValueError("unsupported user-group userset relation")
            projected_subject = f"user_group:{normalized_subject_id}#{relation}"
        else:
            raise ValueError(f"unsupported subject_type: {subject_type}")

        if protected and normalized_subject_type != "user":
            raise ValueError("protected assignments must project a direct user")
        self._validate_source_subject(
            normalized_source_type,
            normalized_subject_type,
        )
        normalized_ref = (source_ref or "").strip()
        locator, normalized_ref = self._source_locator(
            source_type=normalized_source_type,
            source_ref=normalized_ref,
            subject_type=normalized_subject_type,
            subject_id=normalized_subject_id,
            relation=relation,
            include_children=include_children,
        )
        return GrantSourceRecord(
            source_id=source_id,
            subject_type=normalized_subject_type,
            subject_id=normalized_subject_id,
            userset_relation=relation,
            include_children=include_children,
            source_type=normalized_source_type,
            source_ref=normalized_ref,
            source_locator=locator,
            source_fingerprint=_hash(locator),
            projected_subject=projected_subject,
            protected=protected,
        )

    @staticmethod
    def _validate_source_subject(
        source_type: str,
        subject_type: str,
    ) -> None:
        expected_subjects = {
            "DIRECT": {"user"},
            "DEPARTMENT": {"department"},
            "USER_GROUP": {"user_group"},
            "CREATOR": {"user"},
        }
        expected = expected_subjects.get(source_type)
        if expected is not None and subject_type not in expected:
            raise ValueError(f"{source_type} source does not accept {subject_type}")

    @staticmethod
    def _source_locator(
        *,
        source_type: str,
        source_ref: str,
        subject_type: str,
        subject_id: str,
        relation: str | None,
        include_children: bool,
    ) -> tuple[str, str]:
        if source_type == "DIRECT":
            ref = f"{subject_type}:{subject_id}"
            return f"direct:{ref}", ref
        if source_type == "DEPARTMENT":
            ref = f"{subject_id}#{relation}"
            return (
                f"department:{ref}:children={int(include_children)}",
                ref,
            )
        if source_type == "USER_GROUP":
            ref = f"{subject_id}#{relation}"
            return f"user_group:{ref}", ref
        prefixes = {
            "CREATOR": "creator",
            "SPACE_MEMBERSHIP": "space_membership",
            "CHANNEL_MEMBERSHIP": "channel_membership",
            "SNAPSHOT_FROM_PARENT": "snapshot",
            "OTHER": "other",
        }
        if not source_ref:
            raise ValueError(f"{source_type} source_ref must not be empty")
        return f"{prefixes[source_type]}:{source_ref}", source_ref

    def add_source(
        self,
        grant: GrantSnapshot,
        source: GrantSourceRecord,
    ) -> GrantSourceMutation:
        self._ensure_target_model(grant)
        active_sources = tuple(row for row in grant.sources if row.active)
        for existing in active_sources:
            if existing.source_id == source.source_id and (existing.source_fingerprint != source.source_fingerprint):
                raise PermissionVersionConflictError(msg="source ID is bound to another permission source")
            if existing.source_fingerprint == source.source_fingerprint:
                if _source_signature(existing) != _source_signature(source):
                    raise PermissionVersionConflictError(msg="permission source fingerprint collision")
                return GrantSourceMutation(
                    grant=grant,
                    deltas=(),
                    idempotent=True,
                )

        deltas: list[ProjectionTupleDelta] = []
        if not active_sources:
            deltas.extend(
                (
                    self._model_delta(grant, action="WRITE", sequence=0),
                    self._grant_delta(grant, action="WRITE", sequence=1),
                )
            )
        if not self._has_projected_reference(active_sources, source):
            deltas.append(
                self._assignee_delta(
                    grant,
                    source,
                    action="WRITE",
                    sequence=len(deltas),
                )
            )
        updated_sources = tuple(sorted((*active_sources, source), key=lambda row: row.source_id))
        return GrantSourceMutation(
            grant=replace(grant, active=True, sources=updated_sources),
            deltas=tuple(deltas),
        )

    def remove_source(
        self,
        grant: GrantSnapshot,
        *,
        source_id: int,
    ) -> GrantSourceMutation:
        source = next(
            (row for row in grant.sources if row.source_id == source_id and row.active),
            None,
        )
        if source is None:
            raise PermissionVersionConflictError(msg="permission source is missing or already inactive")
        remaining = tuple(row for row in grant.sources if row.active and row.source_id != source_id)
        deltas: list[ProjectionTupleDelta] = []
        if not self._has_projected_reference(remaining, source):
            deltas.append(
                self._assignee_delta(
                    grant,
                    source,
                    action="DELETE",
                    sequence=0,
                )
            )
        if not remaining:
            deltas.extend(
                (
                    self._grant_delta(
                        grant,
                        action="DELETE",
                        sequence=len(deltas),
                    ),
                    self._model_delta(
                        grant,
                        action="DELETE",
                        sequence=len(deltas) + 1,
                    ),
                )
            )
        return GrantSourceMutation(
            grant=replace(
                grant,
                active=bool(remaining),
                sources=remaining,
            ),
            deltas=tuple(deltas),
        )

    def move_source(
        self,
        source_grant: GrantSnapshot,
        target_grant: GrantSnapshot,
        *,
        source_id: int,
    ) -> GrantSourceMoveMutation:
        if source_grant.grant_id == target_grant.grant_id:
            raise ValueError("source and target Grant must differ")
        self._ensure_target_model(target_grant)
        source = next(
            (row for row in source_grant.sources if row.source_id == source_id and row.active),
            None,
        )
        if source is None:
            raise PermissionVersionConflictError(msg="permission source is missing for move")
        removed = self.remove_source(source_grant, source_id=source_id)
        added = self.add_source(
            target_grant,
            replace(source, version=source.version + 1),
        )
        deltas = tuple(replace(delta, sequence=index) for index, delta in enumerate((*removed.deltas, *added.deltas)))
        return GrantSourceMoveMutation(
            source_grant=removed.grant,
            target_grant=added.grant,
            deltas=deltas,
        )

    @staticmethod
    def effective_action_union(
        grants: tuple[GrantSnapshot, ...],
        *,
        projected_subjects: frozenset[str],
    ) -> tuple[str, ...]:
        actions = {
            action
            for grant in grants
            if grant.active and grant.model.active
            if any(source.active and source.projected_subject in projected_subjects for source in grant.sources)
            for action in grant.model.action_codes
        }
        return tuple(sorted(actions))

    @staticmethod
    def _ensure_target_model(grant: GrantSnapshot) -> None:
        if not grant.model.active or not grant.model.action_codes:
            raise PermissionModelStateConflictError(msg=f"permission model {grant.model.model_key} is inactive")

    @staticmethod
    def _has_projected_reference(
        sources: tuple[GrantSourceRecord, ...],
        target: GrantSourceRecord,
    ) -> bool:
        return any(
            source.active
            and source.projected_subject == target.projected_subject
            and source.protected == target.protected
            for source in sources
        )

    @staticmethod
    def _model_delta(
        grant: GrantSnapshot,
        *,
        action: str,
        sequence: int,
    ) -> ProjectionTupleDelta:
        return ProjectionTupleDelta(
            phase="COMMIT",
            sequence=sequence,
            action=action,
            user=f"permission_model:{grant.model.model_key}",
            relation="model",
            object=f"permission_grant:{grant.grant_id}",
        )

    @staticmethod
    def _grant_delta(
        grant: GrantSnapshot,
        *,
        action: str,
        sequence: int,
    ) -> ProjectionTupleDelta:
        return ProjectionTupleDelta(
            phase="COMMIT",
            sequence=sequence,
            action=action,
            user=f"permission_grant:{grant.grant_id}",
            relation="grant",
            object=f"{grant.resource_type}:{grant.resource_id}",
        )

    @staticmethod
    def _assignee_delta(
        grant: GrantSnapshot,
        source: GrantSourceRecord,
        *,
        action: str,
        sequence: int,
    ) -> ProjectionTupleDelta:
        return ProjectionTupleDelta(
            phase="COMMIT",
            sequence=sequence,
            action=action,
            user=source.projected_subject,
            relation=("protected_assignee" if source.protected else "ordinary_assignee"),
            object=f"permission_grant:{grant.grant_id}",
        )

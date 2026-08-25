"""Pure legacy tuple and binding mapper for F048 Grants."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from bisheng.permission.migration.f048_source_inventory import (
    MIGRATED_RESOURCE_TYPES,
    LegacyTupleSource,
    PermissionMigrationResourceDTO,
)

STANDARD_RELATION_MODELS = {
    "viewer": "viewer",
    "can_read": "viewer",
    "editor": "editor",
    "can_edit": "editor",
    "manager": "manager",
    "can_manage": "manager",
    "owner": "owner",
    "can_delete": "owner",
}
PRESERVED_RELATIONS = frozenset(
    {
        "parent",
        "child",
        "shared_with",
        "system",
        "public",
        "member",
        "subtree_member",
        "admin",
    }
)


def _checksum(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LegacyGrantBinding:
    binding_key: str
    tenant_id: int
    resource_type: str
    resource_id: str
    relation: str
    model_source_key: str
    subject_type: str | None = None
    subject_id: str | None = None
    userset_relation: str | None = None
    include_children: bool = False
    source_type: str | None = None
    source_ref: str | None = None
    protected: bool = False


@dataclass(frozen=True, slots=True)
class MappedGrantAssignee:
    assignee_key: str
    subject_type: str
    subject_id: str
    userset_relation: str | None
    include_children: bool
    source_type: str
    source_ref: str
    protected: bool
    source_checksum: str


@dataclass(frozen=True, slots=True)
class MappedGrant:
    grant_key: str
    tenant_id: int
    resource_type: str
    resource_id: str
    model_key: str
    assignees: tuple[MappedGrantAssignee, ...]


@dataclass(frozen=True, slots=True)
class TupleMappingDifference:
    tuple_key: str
    difference_type: str
    message: str
    severity: str = "BLOCKER"


@dataclass(frozen=True, slots=True)
class TupleMappingResult:
    grants: tuple[MappedGrant, ...]
    preserved_tuples: tuple[LegacyTupleSource, ...]
    retired_tuple_keys: tuple[str, ...]
    differences: tuple[TupleMappingDifference, ...]
    blockers: tuple[str, ...]
    deduplicated_count: int
    checksum: str


def _split_object(value: str) -> tuple[str, str]:
    object_type, separator, object_id = value.partition(":")
    if not separator or not object_type or not object_id:
        raise ValueError("invalid OpenFGA object")
    return object_type, object_id


def _split_subject(value: str) -> tuple[str, str, str | None]:
    subject, separator, userset_relation = value.partition("#")
    subject_type, type_separator, subject_id = subject.partition(":")
    if not type_separator or not subject_type or not subject_id:
        raise ValueError("invalid OpenFGA subject")
    return (
        subject_type.casefold(),
        subject_id,
        userset_relation if separator else None,
    )


def compile_department_child_mirrors(
    tuples: tuple[LegacyTupleSource, ...],
) -> tuple[dict[str, str], ...]:
    """Compile the inverse ``child`` facts required by the F048 model.

    Legacy department topology stored only ``department:<parent> parent
    department:<child>``. F048 recursive subtree evaluation requires the
    symmetric ``department:<child> child department:<parent>`` tuple as well.
    """

    parent_by_child = _department_parent_by_child(tuples)
    mirrors: dict[tuple[str, str, str], dict[str, str]] = {}
    for child_id, parent_id in sorted(parent_by_child.items()):
        row = {
            "user": f"department:{child_id}",
            "relation": "child",
            "object": f"department:{parent_id}",
        }
        mirrors[(row["user"], row["relation"], row["object"])] = row

    return tuple(mirrors[key] for key in sorted(mirrors))


def _department_parent_by_child(
    tuples: tuple[LegacyTupleSource, ...],
) -> dict[str, str]:
    parent_by_child: dict[str, str] = {}
    for source in sorted(tuples, key=lambda row: row.key):
        if source.relation != "parent":
            continue
        try:
            object_type, child_id = _split_object(source.object)
            subject_type, parent_id, userset_relation = _split_subject(source.user)
        except ValueError as exc:
            raise ValueError("INVALID_DEPARTMENT_PARENT_TUPLE") from exc
        if object_type != "department" and subject_type != "department":
            continue
        if (
            object_type != "department"
            or subject_type != "department"
            or userset_relation is not None
            or child_id == parent_id
        ):
            raise ValueError("INVALID_DEPARTMENT_PARENT_TUPLE")
        existing_parent = parent_by_child.setdefault(child_id, parent_id)
        if existing_parent != parent_id:
            raise ValueError("MULTIPLE_DEPARTMENT_PARENTS")
    for child_id in parent_by_child:
        seen: set[str] = set()
        cursor = child_id
        while cursor in parent_by_child:
            if cursor in seen:
                raise ValueError("DEPARTMENT_PARENT_CYCLE")
            seen.add(cursor)
            cursor = parent_by_child[cursor]
    return parent_by_child


def _is_strict_department_descendant(
    *,
    candidate_id: str,
    root_id: str,
    parent_by_child: dict[str, str],
) -> bool:
    cursor = candidate_id
    seen: set[str] = set()
    while cursor in parent_by_child:
        if cursor in seen:
            return False
        seen.add(cursor)
        cursor = parent_by_child[cursor]
        if cursor == root_id:
            return candidate_id != root_id
    return False


def _binding_matches(
    binding: LegacyGrantBinding,
    source: LegacyTupleSource,
    *,
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: str,
    userset_relation: str | None,
) -> bool:
    userset_matches = binding.userset_relation in {None, userset_relation}
    if (
        binding.subject_type == "department"
        and binding.include_children
        and binding.userset_relation in {None, "member", "subtree_member"}
        and userset_relation in {"member", "subtree_member"}
    ):
        userset_matches = True
    return (
        binding.tenant_id == source.tenant_id
        and binding.resource_type == resource_type
        and binding.resource_id == resource_id
        and binding.relation == source.relation
        and binding.subject_type in {None, subject_type}
        and binding.subject_id in {None, subject_id}
        and userset_matches
    )


def _binding_matches_department_projection(
    binding: LegacyGrantBinding,
    source: LegacyTupleSource,
    *,
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: str,
    userset_relation: str | None,
    parent_by_child: dict[str, str],
) -> bool:
    return (
        binding.tenant_id == source.tenant_id
        and binding.resource_type == resource_type
        and binding.resource_id == resource_id
        and binding.relation == source.relation
        and binding.subject_type == "department"
        and binding.subject_id is not None
        and binding.include_children
        and subject_type == "department"
        and userset_relation == "member"
        and _is_strict_department_descendant(
            candidate_id=subject_id,
            root_id=binding.subject_id,
            parent_by_child=parent_by_child,
        )
    )


def _assignee(
    source: LegacyTupleSource,
    *,
    subject_type: str,
    subject_id: str,
    userset_relation: str | None,
    binding: LegacyGrantBinding | None,
) -> MappedGrantAssignee:
    include_children = userset_relation == "subtree_member"
    if binding is not None:
        subject_type = binding.subject_type or subject_type
        subject_id = binding.subject_id or subject_id
        if subject_type == "department":
            if binding.userset_relation not in {
                None,
                "member",
                "subtree_member",
            }:
                raise ValueError("BINDING_USERSET_MISMATCH")
            include_children = binding.include_children
            userset_relation = (
                "subtree_member" if include_children else (binding.userset_relation or userset_relation or "member")
            )
        elif binding.include_children:
            raise ValueError("BINDING_USERSET_MISMATCH")
        source_type = binding.source_type or {
            "user": "DIRECT",
            "department": "DEPARTMENT",
            "user_group": "USER_GROUP",
        }.get(subject_type)
        source_ref = binding.source_ref or binding.binding_key
        protected = binding.protected
    else:
        source_type = {
            "user": "DIRECT",
            "department": "DEPARTMENT",
            "user_group": "USER_GROUP",
        }.get(subject_type)
        source_ref = source.key
        protected = False
    if source_type is None:
        raise ValueError("UNSUPPORTED_GRANT_SUBJECT")
    normalized_source_type = source_type.strip().upper()
    payload = {
        "include_children": include_children,
        "protected": protected,
        "source_ref": source_ref,
        "source_type": normalized_source_type,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "userset_relation": userset_relation,
    }
    source_checksum = _checksum(payload)
    return MappedGrantAssignee(
        assignee_key=source_checksum[:32],
        subject_type=subject_type,
        subject_id=subject_id,
        userset_relation=userset_relation,
        include_children=include_children,
        source_type=normalized_source_type,
        source_ref=source_ref,
        protected=protected,
        source_checksum=source_checksum,
    )


def map_legacy_tuples(
    tuples: tuple[LegacyTupleSource, ...],
    bindings: tuple[LegacyGrantBinding, ...],
    *,
    model_key_by_source: dict[str, str],
    resources: tuple[PermissionMigrationResourceDTO, ...] = (),
) -> TupleMappingResult:
    """Convert direct facts only; computed and canonical facts stay untouched."""

    assignees_by_grant: dict[
        tuple[int, str, str, str],
        dict[str, MappedGrantAssignee],
    ] = {}
    preserved: list[LegacyTupleSource] = []
    retired: list[str] = []
    differences: list[TupleMappingDifference] = []
    seen_tuple_keys: set[str] = set()
    resource_by_key = {resource.key: resource for resource in resources}
    private_resource_keys = {resource.key for resource in resources if not resource.migrate_ordinary_grants}
    matched_binding_keys: set[str] = {
        binding.binding_key
        for binding in bindings
        if f"{binding.resource_type}:{binding.resource_id}" in private_resource_keys
    }
    deduplicated_count = 0
    try:
        department_parent_by_child = _department_parent_by_child(tuples)
    except ValueError as exc:
        return TupleMappingResult(
            grants=(),
            preserved_tuples=(),
            retired_tuple_keys=(),
            differences=(
                TupleMappingDifference(
                    tuple_key="department-topology",
                    difference_type=str(exc),
                    message="invalid department parent topology",
                ),
            ),
            blockers=(str(exc),),
            deduplicated_count=0,
            checksum=_checksum({"department_topology_error": str(exc)}),
        )

    for source in sorted(tuples, key=lambda row: row.key):
        if source.key in seen_tuple_keys:
            deduplicated_count += 1
            continue
        seen_tuple_keys.add(source.key)
        resource = resource_by_key.get(source.object)
        if resource is not None and not resource.migrate_ordinary_grants:
            retired.append(source.key)
            differences.append(
                TupleMappingDifference(
                    tuple_key=source.key,
                    difference_type="PRIVATE_RESOURCE_GRANT_RETIRED",
                    message="private resource keeps only its protected creator grant",
                    severity="INFO",
                )
            )
            continue
        if source.relation in PRESERVED_RELATIONS:
            preserved.append(source)
            continue
        try:
            resource_type, resource_id = _split_object(source.object)
            subject_type, subject_id, userset_relation = _split_subject(source.user)
        except ValueError as exc:
            differences.append(
                TupleMappingDifference(
                    tuple_key=source.key,
                    difference_type="INVALID_TUPLE_KEY",
                    message=str(exc),
                )
            )
            continue
        if resource_type not in MIGRATED_RESOURCE_TYPES:
            preserved.append(source)
            continue
        if source.condition:
            differences.append(
                TupleMappingDifference(
                    tuple_key=source.key,
                    difference_type="UNSUPPORTED_TUPLE_CONDITION",
                    message="legacy conditional tuple requires manual mapping",
                )
            )
            continue

        matches = tuple(
            binding
            for binding in bindings
            if _binding_matches(
                binding,
                source,
                resource_type=resource_type,
                resource_id=resource_id,
                subject_type=subject_type,
                subject_id=subject_id,
                userset_relation=userset_relation,
            )
        )
        matched_binding_keys.update(binding.binding_key for binding in matches)
        if len(matches) > 1:
            differences.append(
                TupleMappingDifference(
                    tuple_key=source.key,
                    difference_type="CONFLICTING_BINDINGS",
                    message="tuple matches more than one legacy binding",
                )
            )
            continue
        binding = matches[0] if matches else None
        if binding is None:
            projection_matches = tuple(
                candidate
                for candidate in bindings
                if _binding_matches_department_projection(
                    candidate,
                    source,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    userset_relation=userset_relation,
                    parent_by_child=department_parent_by_child,
                )
            )
            if projection_matches:
                retired.append(source.key)
                continue
        if binding is not None:
            model_key = model_key_by_source.get(binding.model_source_key)
            if model_key is None:
                differences.append(
                    TupleMappingDifference(
                        tuple_key=source.key,
                        difference_type="MISSING_BINDING_MODEL",
                        message=(f"binding references an unmapped legacy model: {binding.model_source_key}"),
                    )
                )
                continue
        else:
            model_key = STANDARD_RELATION_MODELS.get(source.relation)
            if model_key is None:
                differences.append(
                    TupleMappingDifference(
                        tuple_key=source.key,
                        difference_type="UNKNOWN_LEGACY_RELATION",
                        message=f"no F048 model for relation {source.relation}",
                    )
                )
                continue
        try:
            assignee = _assignee(
                source,
                subject_type=subject_type,
                subject_id=subject_id,
                userset_relation=userset_relation,
                binding=binding,
            )
        except ValueError as exc:
            differences.append(
                TupleMappingDifference(
                    tuple_key=source.key,
                    difference_type=str(exc),
                    message="binding and tuple userset facts disagree",
                )
            )
            continue

        if source.tenant_id is None or source.tenant_id <= 0:
            differences.append(
                TupleMappingDifference(
                    tuple_key=source.key,
                    difference_type="MISSING_TUPLE_TENANT",
                    message="migrated resource tuple needs a real tenant",
                )
            )
            continue
        grant_key = (
            source.tenant_id,
            resource_type,
            resource_id,
            model_key,
        )
        by_source = assignees_by_grant.setdefault(grant_key, {})
        by_source.setdefault(assignee.source_checksum, assignee)
        retired.append(source.key)

    for resource in sorted(resources, key=lambda row: row.key):
        if resource.ownership_kind.upper() == "SYSTEM":
            continue
        protected_user_id = (
            resource.creator_user_ids[0]
            if resource.resource_type in {"knowledge_space", "channel"} and len(resource.creator_user_ids) == 1
            else resource.owner_user_id
        )
        if protected_user_id is None or protected_user_id <= 0:
            differences.append(
                TupleMappingDifference(
                    tuple_key=resource.source_locator,
                    difference_type="MISSING_CANONICAL_OWNER",
                    message="user-owned resource has no protected owner fact",
                )
            )
            continue

        grant_key = (
            resource.tenant_id,
            resource.resource_type,
            resource.resource_id,
            "owner",
        )
        by_source = assignees_by_grant.setdefault(grant_key, {})
        protected_subject = str(protected_user_id)
        for source_checksum, existing in tuple(by_source.items()):
            if existing.subject_type == "user" and existing.subject_id == protected_subject and not existing.protected:
                del by_source[source_checksum]
        protected_payload = {
            "include_children": False,
            "protected": True,
            "source_ref": (f"creator:{resource.resource_type}:{resource.resource_id}"),
            "source_type": "CREATOR",
            "subject_id": protected_subject,
            "subject_type": "user",
            "userset_relation": None,
        }
        protected_checksum = _checksum(protected_payload)
        by_source[protected_checksum] = MappedGrantAssignee(
            assignee_key=protected_checksum[:32],
            subject_type="user",
            subject_id=protected_subject,
            userset_relation=None,
            include_children=False,
            source_type="CREATOR",
            source_ref=protected_payload["source_ref"],
            protected=True,
            source_checksum=protected_checksum,
        )

        business_owner_id = resource.owner_user_id
        if (
            resource.migrate_ordinary_grants
            and business_owner_id is not None
            and business_owner_id > 0
            and business_owner_id != protected_user_id
        ):
            ordinary_payload = {
                "include_children": False,
                "protected": False,
                "source_ref": (f"business_owner:{resource.resource_type}:{resource.resource_id}:{business_owner_id}"),
                "source_type": "DIRECT",
                "subject_id": str(business_owner_id),
                "subject_type": "user",
                "userset_relation": None,
            }
            ordinary_checksum = _checksum(ordinary_payload)
            by_source.setdefault(
                ordinary_checksum,
                MappedGrantAssignee(
                    assignee_key=ordinary_checksum[:32],
                    subject_type="user",
                    subject_id=str(business_owner_id),
                    userset_relation=None,
                    include_children=False,
                    source_type="DIRECT",
                    source_ref=ordinary_payload["source_ref"],
                    protected=False,
                    source_checksum=ordinary_checksum,
                ),
            )
            differences.append(
                TupleMappingDifference(
                    tuple_key=resource.source_locator,
                    difference_type="OWNER_FACT_DIVERGENCE_PRESERVED",
                    message=("membership creator and business owner differ; both sources were preserved"),
                    severity="INFO",
                )
            )

    for binding in bindings:
        if binding.binding_key in matched_binding_keys:
            continue
        differences.append(
            TupleMappingDifference(
                tuple_key=f"binding:{binding.binding_key}",
                difference_type="ORPHAN_BINDING",
                message="legacy binding has no matching direct root tuple",
                severity="INFO",
            )
        )

    grants: list[MappedGrant] = []
    for grant_key, by_source in sorted(assignees_by_grant.items()):
        tenant_id, resource_type, resource_id, model_key = grant_key
        canonical_key = "|".join((str(tenant_id), resource_type, resource_id, model_key))
        grants.append(
            MappedGrant(
                grant_key=sha256(canonical_key.encode("utf-8")).hexdigest()[:32],
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
                model_key=model_key,
                assignees=tuple(
                    sorted(
                        by_source.values(),
                        key=lambda row: row.source_checksum,
                    )
                ),
            )
        )

    ordered_differences = tuple(
        sorted(
            differences,
            key=lambda row: (row.tuple_key, row.difference_type),
        )
    )
    blockers = tuple(dict.fromkeys(row.difference_type for row in ordered_differences if row.severity == "BLOCKER"))
    ordered_preserved = tuple(sorted(preserved, key=lambda row: row.key))
    retired_tuple_keys = tuple(sorted(set(retired)))
    payload = {
        "grants": [asdict(grant) for grant in grants],
        "preserved": [row.key for row in ordered_preserved],
        "retired": retired_tuple_keys,
        "differences": [asdict(row) for row in ordered_differences],
    }
    return TupleMappingResult(
        grants=tuple(grants),
        preserved_tuples=ordered_preserved,
        retired_tuple_keys=retired_tuple_keys,
        differences=ordered_differences,
        blockers=blockers,
        deduplicated_count=deduplicated_count,
        checksum=_checksum(payload),
    )

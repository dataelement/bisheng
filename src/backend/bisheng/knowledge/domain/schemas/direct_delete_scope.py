"""Closed, detached physical delete facts; none of these values grants deletion."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from bisheng.knowledge.domain.repositories.knowledge_version_mutation_repository import (
        VersionDocumentFact,
        VersionRowFact,
    )


def _ids(values, *, positions=False):
    if type(values) is not tuple or any(type(value) is not int or value < (0 if positions else 1) for value in values):
        raise ValueError("delete facts require immutable native identifiers")
    if tuple(sorted(set(values))) != values:
        raise ValueError("delete fact identifiers must be unique and ordered")


@dataclass(frozen=True, slots=True)
class DeleteSelection:
    resource_type: Literal["knowledge_file", "folder"]
    resource_id: int

    def __post_init__(self):
        if (
            self.resource_type not in ("knowledge_file", "folder")
            or type(self.resource_id) is not int
            or not 0 < self.resource_id <= 2**63 - 1
        ):
            raise ValueError("a concrete file or folder identifier is required")


@dataclass(frozen=True, slots=True)
class DeleteSelectionIssue:
    positions: tuple[int, ...]
    reason: Literal["not_found", "type_mismatch"]

    def __post_init__(self):
        _ids(self.positions, positions=True)
        if not self.positions or self.reason not in ("not_found", "type_mismatch"):
            raise ValueError("a positioned selection issue is required")


@dataclass(frozen=True, slots=True)
class DeleteResourceFact:
    id: int
    tenant_id: int
    knowledge_id: int
    file_type: int
    file_name: str
    file_level_path: str | None
    level: int | None
    status: int | None
    user_id: int | None
    update_time: datetime | None
    object_names: tuple[str, ...] = field(repr=False)

    def __post_init__(self):
        if (
            any(type(value) is not int or value <= 0 for value in (self.id, self.tenant_id, self.knowledge_id))
            or self.file_type not in (0, 1)
            or type(self.file_type) is not int
        ):
            raise ValueError("invalid physical delete identity")
        if not isinstance(self.file_name, str) or (
            self.file_level_path is not None and not isinstance(self.file_level_path, str)
        ):
            raise ValueError("invalid physical delete path")
        if any(value is not None and type(value) is not int for value in (self.level, self.status, self.user_id)):
            raise ValueError("invalid physical delete scalar")
        if type(self.object_names) is not tuple or any(
            type(value) is not str or not value for value in self.object_names
        ):
            raise ValueError("invalid physical object names")


@dataclass(frozen=True, slots=True)
class DeleteUnit:
    selection_positions: tuple[int, ...]
    resource_ids: tuple[int, ...]
    version_ids: tuple[int, ...]
    deleted_document_ids: tuple[int, ...]
    unregistered_file_ids: tuple[int, ...]
    processing_file_ids: tuple[int, ...]

    def __post_init__(self):
        _ids(self.selection_positions, positions=True)
        for values in (
            self.resource_ids,
            self.version_ids,
            self.deleted_document_ids,
            self.unregistered_file_ids,
            self.processing_file_ids,
        ):
            _ids(values)
        if (
            not self.selection_positions
            or not self.resource_ids
            or not set(self.unregistered_file_ids + self.processing_file_ids) <= set(self.resource_ids)
        ):
            raise ValueError("invalid physical deletion unit")


@dataclass(frozen=True, slots=True)
class DeleteScope:
    tenant_id: int
    space_id: int
    selections: tuple[DeleteSelection, ...]
    resources: tuple[DeleteResourceFact, ...] = ()
    documents: tuple[VersionDocumentFact, ...] = ()
    versions: tuple[VersionRowFact, ...] = ()
    units: tuple[DeleteUnit, ...] = ()
    issues: tuple[DeleteSelectionIssue, ...] = ()
    cleanup_identity: dict = field(default_factory=dict, repr=False)
    object_names: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.tenant_id, self.space_id)):
            raise ValueError("a concrete delete scope is required")
        for values, kind in (
            (self.selections, DeleteSelection),
            (self.resources, DeleteResourceFact),
            (self.units, DeleteUnit),
            (self.issues, DeleteSelectionIssue),
        ):
            if type(values) is not tuple or any(type(value) is not kind for value in values):
                raise ValueError("delete scope facts must be immutable typed tuples")
        if type(self.documents) is not tuple or type(self.versions) is not tuple:
            raise ValueError("original version facts must be immutable tuples")
        if self.cleanup_identity and set(self.cleanup_identity) != {
            "id",
            "name",
            "type",
            "tenant_id",
            "user_id",
            "model",
            "index_name",
            "collection_name",
        }:
            raise ValueError("only the original cleanup identity may be retained")
        object.__setattr__(self, "cleanup_identity", deepcopy(self.cleanup_identity))


def select_delete_scope(scope, positions):
    if positions == tuple(range(len(scope.selections))) and not scope.issues:
        return scope
    remap = {position: index for index, position in enumerate(positions)}
    selected_positions = frozenset(positions)
    units = tuple(
        replace(unit, selection_positions=tuple(remap[pos] for pos in unit.selection_positions))
        for unit in scope.units
        if set(unit.selection_positions) <= selected_positions
    )
    ids = {ident for unit in units for ident in unit.resource_ids}
    version_ids = {ident for unit in units for ident in unit.version_ids}
    documents = {row.document_id for row in scope.versions if row.id in version_ids}
    resources = tuple(row for row in scope.resources if row.id in ids)
    return DeleteScope(
        scope.tenant_id,
        scope.space_id,
        tuple(scope.selections[pos] for pos in positions),
        resources,
        tuple(row for row in scope.documents if row.id in documents),
        tuple(row for row in scope.versions if row.document_id in documents),
        units,
        (),
        scope.cleanup_identity,
        tuple(sorted({name for row in resources for name in row.object_names})),
    )

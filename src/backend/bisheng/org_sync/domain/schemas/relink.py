"""F015 department relink schemas.

Relink is the escape hatch for SSO system migration: when the upstream
HR/LDAP is replaced, existing bisheng departments keep their business
key (``external_id``) but the new source emits different ones. Two
matching strategies are supported:

- ``external_id_map``: the operator supplies an explicit
  ``old_ext → new_ext`` dictionary. Fast, deterministic.
- ``path_plus_name``: best-effort discovery. For each
  ``old_external_id`` the service compares ``(path, name)`` against the
  candidate pool and applies the mapping only when a **single** candidate
  matches. Multi-candidate collisions are persisted to
  :class:`RelinkConflictStore` and returned as ``conflicts`` for an
  operator to resolve manually via
  ``POST /api/v1/internal/departments/relink/resolve-conflict``.

``dry_run=True`` returns ``would_apply`` without writing anything; the
``applied`` list stays empty in that case.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RelinkRequest(BaseModel):
    """Input schema for POST /api/v1/internal/departments/relink."""

    old_external_ids: list[str] = Field(
        default_factory=list,
        description='Existing external_ids to remap to the new source.',
    )
    matching_strategy: Literal['external_id_map', 'path_plus_name']
    external_id_map: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            'Required when matching_strategy="external_id_map". '
            'Maps each old external_id to its replacement.'
        ),
    )
    source: str = Field(
        default='sso',
        description='Department.source field; used for filtering.',
    )
    dry_run: bool = Field(
        default=False,
        description='Return would_apply without writing to the database.',
    )


class RelinkAppliedItem(BaseModel):
    dept_id: int
    old_external_id: str
    new_external_id: str


class RelinkCandidate(BaseModel):
    new_external_id: str
    path: str = ''
    name: str = ''
    score: float = 1.0


class RelinkConflictItem(BaseModel):
    dept_id: int
    old_external_id: str
    candidates: list[RelinkCandidate] = Field(default_factory=list)


class RelinkResponse(BaseModel):
    applied: list[RelinkAppliedItem] = Field(default_factory=list)
    would_apply: list[RelinkAppliedItem] = Field(default_factory=list)
    conflicts: list[RelinkConflictItem] = Field(default_factory=list)


class ResolveConflictRequest(BaseModel):
    """Input schema for POST /api/v1/internal/departments/relink/resolve-conflict."""

    dept_id: int
    chosen_new_external_id: str

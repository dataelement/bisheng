"""One-pass creator-member instructions over complete private original facts.

No membership is promoted, activated or written here. The later builder must
bind these facts to its resource inventory; a value plan is not migration or
permission authority and does not create a new F048 source.
"""

from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.repositories.unification_control_repository import CreatorFact
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    MEMBER_COLUMNS,
    SpaceMembershipHeader,
    SpaceMembershipRow,
)
from bisheng.knowledge.domain.schemas.unification_space_membership import (
    CreatorMembershipPlan,
    _planned_time,
    creator_membership_template,
)
from bisheng.knowledge.domain.services.unification_fingerprints import digest

_ROW_COLUMNS = ("tenant_id", "knowledge_id", *MEMBER_COLUMNS)
_INTS = ("tenant_id", "knowledge_id", "id", "user_id")
_STRINGS = ("business_id", "business_type", "user_role", "status", "membership_source")
_OPTIONAL_STRINGS = (
    "department_admin_promoted_from_role",
    "relation",
    "grant_subject_type",
    "grant_relation",
    "grant_model_id",
    "grant_binding_key",
)


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"creator_membership_{reason}")


def _positive(value):
    return type(value) is int and value > 0


def _raw(row):
    if type(row) is not SpaceMembershipRow:
        _blocked("member_type_invalid")
    values = {name: getattr(row, name) for name in _ROW_COLUMNS}
    if (
        any(type(values[name]) is not int for name in _INTS)
        or any(not _positive(values[name]) for name in ("tenant_id", "knowledge_id", "id"))
        or any(type(values[name]) is not str for name in _STRINGS)
        or any(values[name] is not None and type(values[name]) is not str for name in _OPTIONAL_STRINGS)
        or (values["grant_subject_id"] is not None and type(values["grant_subject_id"]) is not int)
        or any(type(values[name]) is not bool for name in ("grant_include_children", "is_pinned"))
        or any(
            values[name] is not None and type(values[name]) is not datetime for name in ("create_time", "update_time")
        )
        or values["user_role"] not in {"creator", "admin", "member"}
        or values["status"] not in {"ACTIVE", "PENDING", "REJECTED"}
    ):
        _blocked("member_fields_invalid")
    return values


def plan_space_creator_membership(
    header: SpaceMembershipHeader,
    members: tuple[SpaceMembershipRow, ...],
    creator: CreatorFact | None,
    *,
    planned_at: datetime,
) -> CreatorMembershipPlan | None:
    """Sign one complete original set and an insert/keep instruction in O(R)."""
    _planned_time(planned_at)
    if (
        type(header) is not SpaceMembershipHeader
        or not _positive(header.tenant_id)
        or not _positive(header.knowledge_id)
        or type(header.knowledge_type) is not int
        or header.knowledge_type not in (0, 3)
        or (header.creator_user_id is not None and type(header.creator_user_id) is not int)
        or type(header.member_count) is not int
        or header.member_count < 0
        or type(members) is not tuple
        or len(members) != header.member_count
    ):
        _blocked("header_or_complete_set_invalid")
    original, owner, owner_count, other_creator, previous = [], None, 0, False, 0
    for row in members:
        values = _raw(row)
        if (
            values["tenant_id"] != header.tenant_id
            or values["knowledge_id"] != header.knowledge_id
            or values["business_id"] != str(header.knowledge_id)
            or values["business_type"] != "space"
            or values["id"] <= previous
        ):
            _blocked("member_scope_or_order_invalid")
        previous = values["id"]
        original.append(values)
        if values["user_id"] == header.creator_user_id:
            owner, owner_count = values, owner_count + 1
        elif values["user_role"] == "creator":
            other_creator = True
    # Existing SPACE members are preserved as facts, including conflicts.
    # This instruction converts only the original NORMAL resource kind.
    if header.knowledge_type == 3:
        return None
    if (
        not _positive(header.creator_user_id)
        or type(creator) is not CreatorFact
        or not _positive(creator.user_id)
        or creator.user_id != header.creator_user_id
        or creator.exists is not True
        or (creator.delete is not None and type(creator.delete) is not int)
    ):
        _blocked("original_creator_unproven")
    if (
        other_creator
        or owner_count > 1
        or (owner is not None and (owner["user_role"], owner["status"]) != ("creator", "ACTIVE"))
    ):
        _blocked("original_membership_conflict")
    if owner is None:
        template = creator_membership_template(
            knowledge_id=header.knowledge_id, creator_user_id=header.creator_user_id, planned_at=planned_at
        )
    else:
        template = {name: owner[name] for name in MEMBER_COLUMNS if name != "id"}
    return CreatorMembershipPlan(
        tenant_id=header.tenant_id,
        knowledge_id=header.knowledge_id,
        creator_user_id=header.creator_user_id,
        membership_action="insert" if owner is None else "keep",
        before_member_count=header.member_count,
        before_member_digest=digest(original),
        existing_creator_member_id=None if owner is None else owner["id"],
        creator_template_digest=digest(template),
        planned_at=planned_at if owner is None else None,
    )

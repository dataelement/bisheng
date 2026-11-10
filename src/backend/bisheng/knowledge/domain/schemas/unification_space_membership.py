"""Pure creator-membership values; possessing a plan confers no authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError


@dataclass(frozen=True, slots=True)
class CreatorMembershipPlan:
    tenant_id: int
    knowledge_id: int
    creator_user_id: int
    membership_action: Literal["insert", "keep"]
    before_member_count: int
    before_member_digest: str
    existing_creator_member_id: int | None
    creator_template_digest: str
    planned_at: datetime | None


def _planned_time(planned_at):
    if type(planned_at) is not datetime or planned_at.tzinfo is not None or planned_at.microsecond != 0:
        raise KnowledgeOperationPlanConflictError(reason="creator_membership_planned_time_invalid")


def creator_membership_template(*, knowledge_id: int, creator_user_id: int, planned_at: datetime) -> dict:
    """Original SPACE creator defaults with the explicitly signed time.

    These are all actual Member columns except its database-generated ID.
    The migration fixes both timestamps to the plan's naive second, instead
    of invoking the model's creation clock or the database update default.
    """
    if type(knowledge_id) is not int or knowledge_id <= 0 or type(creator_user_id) is not int or creator_user_id <= 0:
        raise KnowledgeOperationPlanConflictError(reason="creator_membership_template_identity_invalid")
    _planned_time(planned_at)
    return {
        "business_id": str(knowledge_id),
        "business_type": "space",
        "user_id": creator_user_id,
        "user_role": "creator",
        "status": "ACTIVE",
        "membership_source": "manual",
        "department_admin_promoted_from_role": None,
        "relation": None,
        "grant_subject_type": None,
        "grant_subject_id": None,
        "grant_relation": None,
        "grant_include_children": False,
        "grant_model_id": None,
        "grant_binding_key": None,
        "is_pinned": False,
        "create_time": planned_at,
        "update_time": planned_at,
    }

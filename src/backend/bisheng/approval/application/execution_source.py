"""Read-only business approval projection, without exposing approval repositories."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType

from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository


@dataclass(frozen=True, slots=True)
class BusinessApproval:
    id: int
    tenant_id: int
    scenario_code: str
    business_resource_type: str
    business_resource_id: str
    business_key: str
    applicant_user_id: int
    status: str
    payload_snapshot: Mapping[str, object]


async def get_business_approval(instance_id: int) -> BusinessApproval | None:
    row = await ApprovalInstanceRepository.get_instance(instance_id)
    if row is None:
        return None
    return _project(row)


async def get_business_approvals(instance_ids: list[int]) -> dict[int, BusinessApproval]:
    """Read bounded batches for business version histories."""
    result = {}
    ids = sorted(set(instance_ids))
    for offset in range(0, len(ids), 100):
        rows = await ApprovalInstanceRepository.get_instances_by_ids(ids[offset : offset + 100])
        result.update({row.id: _project(row) for row in rows})
    return result


def _project(row) -> BusinessApproval:
    return BusinessApproval(
        id=row.id,
        tenant_id=row.tenant_id,
        scenario_code=row.scenario_code,
        business_resource_type=row.business_resource_type,
        business_resource_id=row.business_resource_id,
        business_key=row.business_key,
        applicant_user_id=row.applicant_user_id,
        status=row.status,
        payload_snapshot=MappingProxyType(deepcopy(row.payload_snapshot or {})),
    )

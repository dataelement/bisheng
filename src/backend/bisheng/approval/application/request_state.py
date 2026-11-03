"""Read the current applicant's blocked business requests without changing them."""

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.core.context.tenant import tenant_execution_scope


async def get_failed_request_keys(
    *, tenant_id: int, scenario_code: str, applicant_user_id: int, business_keys: list[str]
) -> frozenset[str]:
    keys = sorted(set(business_keys))
    failed = set()
    for offset in range(0, len(keys), 100):
        with tenant_execution_scope(tenant_id):
            rows = await ApprovalInstanceRepository.list_active_instances_for_business_keys(
                scenario_code=scenario_code,
                applicant_user_id=applicant_user_id,
                business_keys=keys[offset : offset + 100],
            )
        seen = set()
        for row in rows:
            if row.business_key in seen:
                continue
            seen.add(row.business_key)
            if row.status == ApprovalInstanceStatus.EXECUTE_FAILED:
                failed.add(row.business_key)
    return frozenset(failed)

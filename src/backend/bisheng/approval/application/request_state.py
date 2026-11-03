"""Read failed requests in the verified applicant's tenant without changing them."""

from contextlib import contextmanager

from bisheng.approval.domain.repositories.request_state_repository import list_active_request_states
from bisheng.core.context import tenant


@contextmanager
def _applicant_scope(tenant_id: int):
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("tenant_id must be a positive integer")
    bindings = (
        (tenant.current_tenant_id, tenant_id),
        (tenant.visible_tenant_ids, frozenset({tenant_id})),
        (tenant._admin_scope_tenant_id, None),
        (tenant._bypass_tenant_filter, False),
        (tenant._is_management_api, False),
    )
    tokens = [(variable, variable.set(value)) for variable, value in bindings]
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


async def get_failed_request_keys(
    *, tenant_id: int, scenario_code: str, applicant_user_id: int, business_keys: list[str]
) -> frozenset[str]:
    keys = sorted(set(business_keys))
    failed = set()
    for offset in range(0, len(keys), 100):
        with _applicant_scope(tenant_id):
            rows = await list_active_request_states(
                scenario_code=scenario_code,
                applicant_user_id=applicant_user_id,
                business_keys=keys[offset : offset + 100],
            )
        seen = set()
        for key, status in rows:
            if key not in seen:
                seen.add(key)
                if status == "execute_failed":
                    failed.add(key)
    return frozenset(failed)

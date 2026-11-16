"""Public permission ports used by department Owners and SSO composition."""

from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.current_department_repair import (
    KNOWN_EFFECTS,
    archive_owned_key,
    owned_key,
    target_keys,
)
from bisheng.permission.domain.services.projection_diagnostics import (
    emit_projection_alert,
    reason_from_exception,
    relation_diagnostics,
)
from bisheng.permission.domain.services.projection_plan import projection_state_expectations

__all__ = [
    "KNOWN_EFFECTS",
    "archive_owned_key",
    "emit_projection_alert",
    "load_bound_operation_metadata",
    "owned_key",
    "projection_state_expectations",
    "reason_from_exception",
    "relation_diagnostics",
    "target_keys",
]


async def load_bound_operation_metadata(identities):
    return await ProjectionRepository().aget_bound_operation_metadata(identities)

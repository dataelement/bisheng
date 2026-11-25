"""Inspect accepted operations, never authorize repair or probe a remote backend."""

import hashlib
import json

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.common.schemas.api import PageData
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.provider_diagnostics_repository import ProviderDiagnosticsRepository
from bisheng.knowledge.domain.schemas.provider_diagnostics import ProviderOperationDiagnostic
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import is_current_tenant_administrator

_KINDS = {"create_space", "update_space_settings", "upload", "provider_transfer"}
_PHASES = {"create", "settings", "projected", "upload", "reingest", "cutover"}
_STATES = {"pending", "sending", "waiting_remote", "reconciling", "applying", "succeeded", "failed", "manual_review"}


def _diagnostic(row, tenant_id, manifest):
    versions = (
        (item.get("version_id") for item in manifest if isinstance(item, dict)) if isinstance(manifest, list) else ()
    )
    # Whole target tuple, not a suffix of a possibly sensitive opaque ID. Salt
    # the namespace with tenant/space so labels cannot correlate across scopes.
    frozen = json.dumps(
        [tenant_id, row.space_id, row.provider_instance_id, row.remote_scope_id, row.remote_kb_id],
        separators=(",", ":"),
    )
    return ProviderOperationDiagnostic(
        operation_id=row.operation_id,
        kind=row.kind if row.kind in _KINDS else "unknown",
        space_id=row.space_id,
        version_ids=list(dict.fromkeys(v for v in versions if type(v) is int and 0 < v < 2**53)),
        remote_target="target-" + hashlib.sha256(frozen.encode()).hexdigest()[:16],
        generation=row.generation,
        phase=row.phase if row.phase in _PHASES else "unknown",
        state=row.state if row.state in _STATES else "unknown",
        error_code=row.last_error_code
        if row.last_error_code in {None, "not_received", "manual_review_required"}
        else "unknown",
        attempt=row.attempt,
        capability_revision=row.capability_revision,
        create_time=row.create_time,
    )


async def list_provider_operations(identity, space_id, page, page_size):
    tenant_id = get_current_tenant_id()
    if not tenant_id or is_tenant_filter_bypassed() or not await is_current_tenant_administrator(identity):
        raise UnAuthorizedError()
    repo = ProviderDiagnosticsRepository()
    async with get_async_db_session() as session:
        if not await repo.has_space(session, tenant_id, space_id):
            raise SpaceNotFoundError()
    # Match the existing task-records read gate. Release the connection first:
    # the F048 target loader needs its own session.
    await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
    async with get_async_db_session() as session:
        count, rows, manifests = await repo.list_rows(session, tenant_id, space_id, page, page_size)
    return PageData[ProviderOperationDiagnostic](
        total=count, data=[_diagnostic(row, tenant_id, manifests.get(row.operation_id)) for row in rows]
    )

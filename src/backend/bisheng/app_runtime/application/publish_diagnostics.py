"""Read expiring diagnostics through the app owner's edit-authorized boundary."""

from datetime import datetime

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
from bisheng.app_runtime.domain.services.runtime_public_diagnostics import bounded_tail, stored_failure


async def publish_failure(deployment, *, actor, repository=None, now=None):
    from bisheng.app_runtime.application.authorization import authorize_app

    if not deployment.failure:
        return None
    await authorize_app(actor, deployment.app_id, "log_read")
    result = stored_failure(deployment.failure)
    if not isinstance(result, dict):
        return result
    details = result.get("details")
    if not isinstance(details, dict) or not details.get("operation_id"):
        return result
    details.update(tail=[], diagnostics_available=False)
    repo = repository or RuntimeDeliveryRepository()
    app = await repo.get_application(deployment.app_id)
    if app is None or app.tenant_id != deployment.tenant_id:
        return result
    operation = await repo.get(RuntimeOperation, details["operation_id"])
    if (
        operation is None
        or (operation.tenant_id, operation.app_id) != (deployment.tenant_id, deployment.app_id)
        or operation.version_id != deployment.version_id
        or (operation.deployment_id and operation.deployment_id != deployment.id)
        or operation.diagnostics_until is None
        or operation.diagnostics_until <= (now or datetime.utcnow())
    ):
        return result
    # The backend redacted this value when recording the fact. Public reads never unseal payloads.
    details["tail"] = bounded_tail((operation.failure or {}).get("diagnostic_tail", ""))
    details["diagnostics_available"] = bool(details["tail"])
    return result


__all__ = ["publish_failure", "stored_failure"]

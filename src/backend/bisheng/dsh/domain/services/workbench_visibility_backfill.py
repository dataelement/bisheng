"""One-time upgrade backfill: keep pre-3.0 workbench models visible to every member.

Before 3.0 the workbench ``models`` list (``linsight_llm`` system-model config) was
the set of models users could pick in daily chat and task mode. With DSH enabled
the picker is driven by ``dsh_model_visibility`` instead, and a model without a
visibility row is visible to nobody — so an upgraded deployment showed users an
empty model list. New dialogue models get ``everyone=True`` when they are created
(``new_model_visibility``); this backfill gives the same grant to the models an
upgraded tenant already exposed.

Per active tenant, once:
- models come from the tenant's effective ``linsight_llm`` config (own row, or the
  Root row it inherits); ids that are not existing ``llm`` models are dropped;
- a tenant that already has any visibility row is already governed by DSH
  visibility (an unconfigured model there may be off on purpose) and is skipped,
  unless an operator passes ``include_configured`` from the CLI; even then a
  model that has a row is left as configured;
- a tenant holding unmigrated legacy DSH grants (``dsh_user_policy`` /
  ``dsh_subject_policy``) is skipped: ``migrate_unified_credits`` must import
  those grants first, and it refuses to run once any visibility row exists;
- an audit row marks the tenant done, so an admin who later turns "visible to
  all members" off is never overridden by a restart.

Runs automatically on startup (``main.lifespan``) and as a CLI
(``scripts/backfill_workbench_upgrade.py``).
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlmodel import Session, select

from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy
from bisheng.dsh.domain.models.unified_policy import ModelVisibility, UnifiedPolicyAudit
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import ModelVisibilityInput
from bisheng.dsh.domain.services.legacy_credit_migration import MIGRATION_RESOURCE as LEGACY_MIGRATION_RESOURCE

BACKFILL_RESOURCE = "migration:workbench-visibility-v1"
# Recorded as updated_by / actor on rows written by the startup backfill.
SYSTEM_ACTOR_ID = 0


def workbench_model_ids(config_value: str | None) -> list[int]:
    """Model ids listed in a ``linsight_llm`` config value, in order, without duplicates."""
    if not config_value:
        return []
    try:
        payload = json.loads(config_value)
    except (TypeError, ValueError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    ids: list[int] = []
    for model in models if isinstance(models, list) else []:
        raw = model.get("id") if isinstance(model, dict) else None
        try:
            model_id = int(raw)
        except (TypeError, ValueError):
            continue
        if model_id > 0 and model_id not in ids:
            ids.append(model_id)
    return ids


def backfill_tenant_visibility(
    session: Session,
    model_ids: list[int],
    *,
    actor_id: int = SYSTEM_ACTOR_ID,
    apply: bool = False,
    include_configured: bool = False,
) -> dict[str, Any]:
    """Grant ``everyone`` to the current tenant's unconfigured workbench models, once."""
    tenant = require_tenant()
    repo = UnifiedPolicyRepository(session)
    if apply:
        # Serialize with admin edits and with other nodes running the same startup.
        repo.memberships._lock_tenant()
    with strict_tenant_filter():
        done = session.exec(select(UnifiedPolicyAudit).where(UnifiedPolicyAudit.resource == BACKFILL_RESOURCE)).first()
        if done:
            return {"tenant_id": tenant, "state": "already_applied"}
        legacy_imported = session.exec(
            select(UnifiedPolicyAudit).where(UnifiedPolicyAudit.resource == LEGACY_MIGRATION_RESOURCE)
        ).first()
        legacy = session.exec(select(DshUserPolicy.id)).first() or session.exec(select(DshSubjectPolicy.id)).first()
        if legacy and not legacy_imported:
            return {"tenant_id": tenant, "state": "skipped_legacy_grants"}
        configured = set(session.exec(select(ModelVisibility.model_id)).all())
    if configured and not include_configured:
        return {"tenant_id": tenant, "state": "skipped_configured"}
    granted = [model_id for model_id in model_ids if model_id not in configured]
    summary = {"granted": granted, "kept": [model_id for model_id in model_ids if model_id in configured]}
    if apply:
        for model_id in granted:
            repo.save_visibility(model_id, actor_id, ModelVisibilityInput(version=0, everyone=True))
        repo._audit(actor_id, BACKFILL_RESOURCE, None, summary)
    return {"tenant_id": tenant, "state": "applied" if apply else "preview", **summary}


def _existing_llm_ids(session: Session, model_ids: list[int]) -> list[int]:
    from bisheng.llm.domain.models.llm_server import LLMModel

    if not model_ids:
        return []
    with bypass_tenant_filter():
        rows = session.exec(select(LLMModel.id).where(LLMModel.id.in_(model_ids), LLMModel.model_type == "llm")).all()
    present = set(rows)
    return [model_id for model_id in model_ids if model_id in present]


def backfill_workbench_model_visibility(
    apply: bool = True,
    *,
    actor_id: int = SYSTEM_ACTOR_ID,
    tenant_id: int | None = None,
    include_configured: bool = False,
) -> dict[str, Any]:
    """Run the per-tenant backfill over every active tenant (or one tenant)."""
    from bisheng.common.models.config import ConfigKeyEnum
    from bisheng.core.database import get_sync_db_session
    from bisheng.database.models.tenant import Tenant
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfigDao

    with get_sync_db_session() as session, bypass_tenant_filter():
        statement = select(Tenant.id).where(Tenant.status == "active").order_by(Tenant.id)
        if tenant_id is not None:
            statement = statement.where(Tenant.id == tenant_id)
        tenant_ids = list(session.exec(statement).all())

    results: list[dict[str, Any]] = []
    for tid in tenant_ids:
        try:
            with bypass_tenant_filter():
                value, _inherited, _blocked = TenantSystemModelConfigDao.resolve(tid, ConfigKeyEnum.LINSIGHT_LLM.value)
            with get_sync_db_session() as session:
                model_ids = _existing_llm_ids(session, workbench_model_ids(value))
                with profile_scope(tid):
                    result = backfill_tenant_visibility(
                        session, model_ids, actor_id=actor_id, apply=apply, include_configured=include_configured
                    )
                if apply:
                    session.commit()
                else:
                    session.rollback()
        except Exception as error:
            # One tenant's failure must not block the others or startup; it is retried next start.
            logger.exception("workbench model visibility backfill failed for tenant={}", tid)
            result = {"tenant_id": tid, "state": "error", "reason": str(error)}
        results.append(result)

    granted = sum(len(row.get("granted", [])) for row in results if row["state"] == "applied")
    if apply and granted:
        logger.info("workbench model visibility backfill granted everyone on {} model(s)", granted)
    return {
        "apply": apply,
        "tenants": len(results),
        "granted": granted,
        "errors": sum(1 for row in results if row["state"] == "error"),
        "rows": results,
    }

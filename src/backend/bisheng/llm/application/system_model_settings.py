"""Administrative repair diagnostics; these records never admit model execution."""

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.application.model_default import ModelDefaultApplication, current_model_default_tenant
from bisheng.llm.application.model_default_read import get_model_default_read_runtime
from bisheng.llm.domain.models.llm_server import LLMDao
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_SCHEMAS,
    extract_model_default_references,
    model_default_slot_types,
)


def diagnose_model_reference(reference, model, server, *, tenant_id, shared_server_ids, config_key="evaluation_llm"):
    """Expose only names of own/Root references already present in the configuration."""
    status = "available"
    name = None
    if model is None or server is None:
        status = "missing"
    elif model.tenant_id not in {tenant_id, ROOT_TENANT_ID} or server.tenant_id != model.tenant_id:
        status = "outside_tenant"
    else:
        name = model.model_name
        if model.tenant_id != tenant_id and model.server_id not in shared_server_ids:
            status = "not_shared"
        elif not model.online:
            status = "offline"
        elif model.model_type not in model_default_slot_types(config_key, reference.slot_key):
            status = "wrong_type"
    return {
        "slot_key": reference.slot_key,
        "model_id": int(reference.target.target_id),
        "model_name": name,
        "status": status,
    }


async def read_system_model_settings(login_user, *, include_impact=False):
    tenant = current_model_default_tenant()
    await ModelDefaultApplication._authorize(login_user, tenant)
    runtime = get_model_default_read_runtime()
    sections = []
    async with get_async_db_session() as session:
        for key, schema in MODEL_DEFAULT_SCHEMAS.items():
            raw = await runtime.aget_default(key, login_user=login_user, session=session)
            config = schema.model_validate_json(raw.payload_json)
            references = extract_model_default_references(key, config)
            sections.append((key, raw, references))
    model_ids = sorted({int(ref.target.target_id) for _, _, refs in sections for ref in refs})
    models = {}
    # Keep repair reads bounded without dropping references from the response.
    with bypass_tenant_filter():
        for offset in range(0, len(model_ids), 200):
            models.update({row.id: row for row in await LLMDao.aget_model_by_ids(model_ids[offset : offset + 200])})
        server_ids = sorted({row.server_id for row in models.values() if row.server_id})
        servers = {}
        for offset in range(0, len(server_ids), 200):
            servers.update({row.id: row for row in await LLMDao.aget_server_by_ids(server_ids[offset : offset + 200])})
    shared = (
        frozenset(await LLMDao.aget_shared_server_ids_for_leaf(tenant, raise_on_error=True))
        if tenant != ROOT_TENANT_ID and model_ids
        else frozenset()
    )
    await ModelDefaultApplication._authorize(login_user, current_model_default_tenant(tenant))
    result = {
        "tenant_id": tenant,
        "sections": [
            {
                "key": key,
                "inherited_from_root": raw.inherited_from_root,
                "fallback_blocked": raw.fallback_blocked,
                "references": [
                    diagnose_model_reference(
                        reference,
                        models.get(int(reference.target.target_id)),
                        servers.get(getattr(models.get(int(reference.target.target_id)), "server_id", None)),
                        tenant_id=tenant,
                        shared_server_ids=shared,
                        config_key=key,
                    )
                    for reference in references
                ],
            }
            for key, raw, references in sections
        ],
    }
    if include_impact and tenant == ROOT_TENANT_ID:
        from bisheng.llm.application.model_sharing_status import ModelSharingStatusService
        from bisheng.llm.domain.repositories.system_model_settings_repository import inheriting_children

        async with get_async_db_session() as session:
            children = await inheriting_children(session, tuple(MODEL_DEFAULT_SCHEMAS))
        coverage = {}
        service = ModelSharingStatusService()
        for server_id in server_ids:
            if servers[server_id].tenant_id == ROOT_TENANT_ID:
                status = await service.aget(identity=login_user, server_id=server_id)
                coverage[server_id] = frozenset(status["shared_child_ids"])
        for section in result["sections"]:
            section["inheritance_impact"] = [
                {
                    "slot_key": ref["slot_key"],
                    "model_id": ref["model_id"],
                    "missing_tenant_ids": [
                        child
                        for child in children[section["key"]]
                        if child not in coverage.get(getattr(models.get(ref["model_id"]), "server_id", None), ())
                    ],
                }
                for ref in section["references"]
            ]
    return result

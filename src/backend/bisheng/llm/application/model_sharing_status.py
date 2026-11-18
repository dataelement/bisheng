"""Authenticated, credential-free provider intent and actual coverage."""

from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.application.model_deletion_context import model_deletion_request, model_write_phase
from bisheng.llm.application.model_sharing import ModelSharingApplication


class ModelSharingStatusService:
    def __init__(self, sharing=None):
        self.sharing = sharing if sharing is not None else ModelSharingApplication()

    async def aget(self, *, identity, server_id, include_coverage=True):
        app = self.sharing
        async with model_deletion_request(identity, references=app.references, plans=app.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            async with model_write_phase(app.session_factory, request) as phase:
                provider = await phase.call(app.providers.alock_provider, phase.session, server_id=server_id)
                if provider.tenant_id != ROOT_TENANT_ID:
                    raise LLMModelNotAccessibleError()
                intent = await phase.call(app.intents.aread, phase.session, server_id=server_id)
                plan = await phase.call(app.providers.aactive_plan, phase.session, server_id=server_id)
                if plan is not None:
                    app.providers.validate(plan)
                expected = (
                    await phase.call(app.intents.aactive_children, phase.session)
                    if include_coverage and intent is not None and intent.enabled
                    else ()
                )
                result = {
                    "enabled": intent.enabled if intent else None,
                    "version": intent.version if intent else 0,
                    "plan_id": intent.plan_id if intent else None,
                    "active_plan": {"id": plan.id, "state": plan.model_execution_state, "operation": plan.operation}
                    if plan
                    else None,
                }
            if not include_coverage:
                return result
            sharing = await app._permission(request)
            snapshot = await request.call(sharing.aread, server_id=server_id)
            return {
                **result,
                "shared_child_ids": list(snapshot.subjects),
                "expected_child_ids": list(expected),
                "missing_child_ids": sorted(set(expected) - set(snapshot.subjects)),
            }

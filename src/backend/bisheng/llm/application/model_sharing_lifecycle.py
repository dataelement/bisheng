"""Model-owner lifecycle work in the original provider-locked transaction."""

from bisheng.dsh.domain.services.shared_model_visibility import initialize_shared_model_visibility
from bisheng.llm.domain.repositories.model_sharing_intent_repository import ModelSharingIntentRepository


async def initialize_sharing_update(session, *, request, server_id, plan_id, enabled, new_model_ids, prepared_sharing):
    repository = ModelSharingIntentRepository()
    # A Root update includes an explicit sharing command. Its durable intent is
    # committed together with the original update plan's COMPLETED state.
    await repository.aset(session, server_id=server_id, enabled=enabled, plan_id=plan_id)
    receipt = await repository.aread_initialization(session, plan_id=plan_id)
    if receipt is not None:
        await initialize_shared_model_visibility(
            session,
            child_ids=receipt.child_ids,
            model_ids=receipt.model_ids,
            actor_user_id=request.actor.subject_id,
            plan_id=plan_id,
            guard=request.check,
        )
    if enabled and new_model_ids and prepared_sharing is not None:
        ids = await repository.adialogue_model_ids(session, server_id=server_id, model_ids=new_model_ids)
        await initialize_shared_model_visibility(
            session,
            child_ids=prepared_sharing.after,
            model_ids=ids,
            actor_user_id=request.actor.subject_id,
            plan_id=plan_id,
            guard=request.check,
        )


async def prepare_added_provider_models(*, server_id, identity):
    """Freeze permission reads outside SQL; the writer rechecks intent version."""
    from copy import deepcopy

    from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
    from bisheng.llm.application.model_deletion_context import model_deletion_request, model_write_phase
    from bisheng.llm.application.model_sharing import get_model_sharing_application

    if identity is None:
        raise LLMModelNotAccessibleError()
    app = await get_model_sharing_application()
    async with model_deletion_request(identity, references=app.references, plans=app.plans) as request:
        if request.tenant_id != 1 or not request.actor.super_admin:
            raise LLMModelNotAccessibleError()
        await app._recover_previous(request, server_id=server_id)
        async with model_write_phase(app.session_factory, request) as phase:
            await phase.call(app.providers.alock_provider, phase.session, server_id=server_id)
            await phase.call(app.providers.arequire_idle, phase.session, server_id=server_id)
            intent = await phase.call(app.intents.aread, phase.session, server_id=server_id)
            pin = (intent.enabled, intent.version, intent.plan_id) if intent else (None, 0, None)
        subjects = ()
        if pin[0] or pin[0] is None:
            sharing = await app._permission(request)
            subjects = (await request.call(sharing.aread, server_id=server_id)).subjects
        if pin[0] is None and subjects:
            await request.call(
                app.arepair_enabled_sharing,
                identity=identity,
                server_id=server_id,
                expected_enabled=None,
                expected_version=0,
                expected_plan_id=None,
                adopt_only=True,
            )
            return await prepare_added_provider_models(server_id=server_id, identity=identity)
        return {"pin": pin, "subjects": subjects, "actor": deepcopy(request.actor_reference)}


async def initialize_added_provider_models(session, *, server_id, model_ids, identity, sharing_snapshot):
    """Consume the snapshot only in the caller's original provider transaction."""
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
    from bisheng.llm.application.model_deletion_context import model_deletion_request
    from bisheng.llm.application.model_sharing import get_model_sharing_application

    repository = ModelSharingIntentRepository()
    intent = await repository.aread(session, server_id=server_id)
    pin = (intent.enabled, intent.version, intent.plan_id) if intent else (None, 0, None)
    if sharing_snapshot is None or pin != sharing_snapshot["pin"]:
        raise KnowledgeOperationPlanChangedError()
    if not pin[0]:
        return
    app = await get_model_sharing_application()
    async with model_deletion_request(identity, references=app.references, plans=app.plans) as request:
        if request.actor_reference != sharing_snapshot["actor"]:
            raise KnowledgeOperationPlanChangedError()
        ids = await repository.adialogue_model_ids(session, server_id=server_id, model_ids=model_ids)
        await initialize_shared_model_visibility(
            session,
            child_ids=sharing_snapshot["subjects"],
            model_ids=ids,
            actor_user_id=request.actor.subject_id,
            plan_id=intent.plan_id,
            guard=request.check,
        )

"""Private Knowledge model reads preserve original ambient execution identity."""

from dataclasses import dataclass
from weakref import WeakKeyDictionary, ref

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import (
    get_visible_tenant_ids,
    is_management_all_tenants,
    is_tenant_filter_bypassed,
)
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.contracts import TransactionIdentity, canonical_target_id
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_contracts import (
    ReadIdentityFacts,
    canonical_payload_json,
    payload_digest,
)
from bisheng.utils.async_utils import run_async_safe


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _KnowledgeModelIdentity:
    knowledge_id: int
    tenant_id: int


class KnowledgeModelReadIdentityPort:
    def __init__(self, repository=None):
        self.repository = repository if repository is not None else KnowledgeModelReferenceRepository()
        self._issued = WeakKeyDictionary()
        self._authenticated = AuthenticatedSourceReadIdentity()

    @staticmethod
    def _ambient():
        tenant = _resolve_tenant_id()
        actor = get_current_permission_actor()
        principal = get_current_open_api_principal()
        public = get_current_public_api_principal()
        if (
            type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or (principal is not None and public is not None)
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_model_read_context")
        background = None
        if actor is None:
            if principal is not None or public is not None:
                raise ResourceReferenceInvalidError(reason="knowledge_model_original_actor_required")
            # Only the actual Celery signal issues this provenance. Numeric
            # tenant ContextVars and ordinary execution scopes grant no proof.
            from bisheng.core.context.background_execution import get_current_background_task

            background = get_current_background_task()
            if background is None or background.tenant_id != tenant:
                raise ResourceReferenceInvalidError(reason="knowledge_model_background_provenance_required")
        visible = get_visible_tenant_ids()
        try:
            fingerprint = payload_digest(
                canonical_payload_json(
                    {
                        "request_tenant_id": tenant,
                        "actor": {
                            "subject_type": actor.subject_type,
                            "subject_id": actor.subject_id,
                            "tenant_id": actor.current_tenant_id,
                            "super_admin": actor.super_admin,
                            "tenant_admin_ids": sorted(actor.tenant_admin_tenant_ids),
                            "data_scope": actor.data_scope,
                        }
                        if actor is not None
                        else None,
                        "open_api": principal.model_dump(mode="json") if principal is not None else None,
                        "public_api": public.model_dump(mode="json") if public is not None else None,
                        "background": {
                            "tenant_id": background.tenant_id,
                            "task_id": background.task_id,
                            "task_name": background.task_name,
                        }
                        if background is not None
                        else None,
                        "visible_tenant_ids": sorted(visible) if visible is not None else None,
                        "management_all_tenants": is_management_all_tenants(),
                        "trace_id": trace_id_var.get(),
                    }
                )
            )
        except (TypeError, ValueError, AttributeError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_identity_invalid") from error
        return ReadIdentityFacts(tenant, fingerprint), actor, principal, public, background

    def _issue(self, session, knowledge_id, row):
        facts, *originals = self._ambient()
        if row is None or row["tenant_id"] != facts.request_tenant_id:
            raise ResourceReferenceInvalidError(reason="knowledge_model_internal_source_not_owned")
        identity = _KnowledgeModelIdentity(knowledge_id, facts.request_tenant_id)
        self._issued[identity] = (
            ref(identity),
            TransactionIdentity.capture(session),
            (identity.knowledge_id, identity.tenant_id),
            facts,
            tuple(originals),
        )
        return identity

    def issue(self, session, knowledge_id):
        knowledge_id = int(canonical_target_id(knowledge_id))
        row = self.repository.load_source(session, knowledge_id)
        return self._issue(session, knowledge_id, row)

    async def aissue(self, session, knowledge_id):
        knowledge_id = int(canonical_target_id(knowledge_id))
        row = await self.repository.aload_source(session, knowledge_id)
        return self._issue(session, knowledge_id, row)

    def _registration(self, identity):
        registered = self._issued.get(identity) if isinstance(identity, _KnowledgeModelIdentity) else None
        if (
            registered is None
            or registered[0]() is not identity
            or (identity.knowledge_id, identity.tenant_id) != registered[2]
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_model_identity_not_issued")
        try:
            registered[1].assert_current(registered[1].session)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_identity_transaction") from error
        current, *originals = self._ambient()
        if current != registered[3] or any(a is not b for a, b in zip(originals, registered[4], strict=True)):
            raise ResourceReferenceInvalidError(reason="knowledge_model_identity_context_changed")
        return registered

    def assert_source(self, session, identity, knowledge_id):
        registered = self._registration(identity)
        try:
            registered[1].assert_current(session)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_identity_transaction") from error
        if identity.knowledge_id != knowledge_id:
            raise ResourceReferenceInvalidError(reason="knowledge_model_identity_source_changed")
        return registered[4][0]

    def capture(self, identity):
        if isinstance(identity, UserPayload):
            return run_async_safe(self._authenticated.acapture(identity))
        return self._registration(identity)[3]

    async def acapture(self, identity):
        if isinstance(identity, UserPayload):
            return await self._authenticated.acapture(identity)
        return self._registration(identity)[3]

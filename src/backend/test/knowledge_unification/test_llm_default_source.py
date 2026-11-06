"""T468: defaults read actual original storage without inventing a person.

覆盖 AC: AC-71, AC-87, AC-89, AC-91, AC-92
"""

from copy import copy

import pytest
from sqlalchemy import update
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.database.models.tenant import Tenant
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from test.knowledge_unification import test_llm_default_repository as defaults
from test.knowledge_unification.test_ref_repo import tenant

store = defaults.store
astore = defaults.astore
model_owner_tenant = defaults.model_owner_tenant
REQUEST = SourceReadRequest("model_default", "evaluation_llm", "current")


def graph():
    identity = ModelDefaultReadIdentityPort()
    owner = ModelDefaultSourceOwner(identity_port=identity)
    return identity, owner, SourceReadVerifier({"model_default": owner}, identity)


def test_native_ambient_identity_reads_actual_root_source_and_preserves_request_tenant(store):
    identity, owner, verifier = graph()
    original = identity.issue_identity()
    with Session(store) as session:
        scope = verifier.issue_scope(session, REQUEST, original)
        snapshot = verifier.get_source_snapshot(session, scope, original)
        assert snapshot.source_key.tenant_id == 1
        assert snapshot.source_key.source_id == "evaluation_llm" and snapshot.source_key.source_version == "current"
        assert snapshot.payload_json == '{"model_id":99}' and snapshot.references[0].target.target_id == "99"
        assert get_current_tenant_id() == 101 and not session.identity_map
        assert owner.resolve_source(session, REQUEST, original) == snapshot


async def test_async_own_invalid_id_is_still_in_complete_raw_snapshot(astore):
    identity, owner, verifier = graph()
    original = identity.issue_identity()
    async with AsyncSession(astore) as session:
        await ModelDefaultRepository().aput(session, "evaluation_llm", '{"model_id":777}')
        scope = await verifier.aissue_scope(session, REQUEST, original)
        snapshot = await verifier.aget_source_snapshot(session, scope, original)
        assert snapshot.source_key.tenant_id == 101 and snapshot.references[0].target.target_id == "777"
        assert snapshot.payload_json == '{"model_id":777}'
        assert await owner.aresolve_source(session, REQUEST, original) == snapshot
        await session.rollback()


@pytest.mark.parametrize("kind", ["copy", "tenant", "bypass", "raw_user"])
def test_domain_identity_is_private_and_exactly_bound_to_ambient_context(store, kind):
    identity, _, verifier = graph()
    original = identity.issue_identity()
    if kind == "copy":
        original = copy(original)
    elif kind == "raw_user":
        original = UserPayload(user_id=7, user_name="raw", tenant_id=101)
    with Session(store) as session:
        if kind == "bypass":
            with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
                verifier.issue_scope(session, REQUEST, original)
        else:
            with tenant(202 if kind == "tenant" else 101), pytest.raises(ResourceReferenceInvalidError):
                verifier.issue_scope(session, REQUEST, original)


def test_original_user_home_does_not_replace_management_pin_and_roles_remain_bound(store):
    user = UserPayload(user_id=7, user_name="super", tenant_id=1, user_role=[], is_global_super=True)
    identity, _, verifier = graph()
    actor = PermissionActor(subject_id=7, tenant_id=101, super_admin=True)
    token = set_current_permission_actor(actor)
    try:
        original = identity.issue_identity(user)
        assert identity.capture(original).request_tenant_id == 101 and original.login_user is user
        with Session(store) as session:
            scope = verifier.issue_scope(session, REQUEST, original)
            changed = set_current_permission_actor(
                PermissionActor(subject_id=7, tenant_id=101, super_admin=True, data_scope="personal_only")
            )
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    verifier.get_source_snapshot(session, scope, original)
            finally:
                reset_current_permission_actor(changed)
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize(
    "key,version", [("workbench", "current"), ("knowledge_llm", "other"), ("assistant_llm", "current")]
)
def test_only_real_current_config_sources_can_be_issued(store, key, version):
    identity, _, verifier = graph()
    with Session(store) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            verifier.issue_scope(session, SourceReadRequest("model_default", key, version), identity.issue_identity())


async def test_current_revalidation_checks_real_inheritance_policy_again(astore):
    identity, owner, _ = graph()
    original = identity.issue_identity()
    async with AsyncSession(astore) as session:
        before = await owner.aresolve_source(session, REQUEST, original)
        await session.execute(update(Tenant).where(Tenant.id == 1).values(share_default_to_children=0))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.arevalidate_source(session, REQUEST, original, before)


def test_source_owner_rejects_identity_from_another_default_authority(store):
    one, _, _ = graph()
    _, other_owner, _ = graph()
    with Session(store) as session, pytest.raises(ResourceReferenceInvalidError):
        other_owner.resolve_source(session, REQUEST, one.issue_identity())

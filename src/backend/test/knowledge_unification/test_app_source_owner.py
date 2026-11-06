"""Real APP UUID/version/current credential facts. 覆盖 AC: AC-37, AC-68, AC-87, AC-89, AC-91, AC-92."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.application import reference_source_owner as module
from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
from bisheng.app_publish.domain.services.preview_access_service import PreviewQualification
from bisheng.app_publish.domain.services.reference_extractor import (
    APP_REFERENCE_EXTRACTOR_VERSION,
    extract_app_reference_requests,
)
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation, RuntimeRoute
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceType, TargetKey, reference_set_digest
from bisheng.resource_reference.application.source_contracts import SourceReadRequest, canonical_payload_json
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_app_resolution as resolution_fixtures
from test.knowledge_unification.test_app_read_identity import principal

ctx = resolution_fixtures.ctx
resolving = resolution_fixtures.resolving
VERSION = "59b041ff-931f-4bc2-8d42-8b8a2dc40487"
HISTORY = "d762d1c3-e490-41c6-b8e0-a6ceff2600cd"


@pytest.fixture
async def application(resolving, monkeypatch):
    engine, _, names = resolving
    identity = principal()
    models = (
        App,
        AppVersion,
        HostedAppSubject,
        ApiCredential,
        AppPreviewSession,
        RuntimeRoute,
        RuntimeCredentialBinding,
        RuntimeOperation,
        BusinessReferenceSet,
        BusinessResourceReference,
    )
    metadata = sa.MetaData()
    for model in models:
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    col.name,
                    col.type.copy(),
                    primary_key=col.primary_key,
                    nullable=col.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if col.name in {"create_time", "update_time"}
                    else col.server_default,
                )
                for col in model.__table__.columns
            ],
        )
    declaration = {"models": [{"name": "alpha"}], "knowledge_bases": [{"id": "7"}]}
    from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration

    requests = extract_app_reference_requests(CapabilityDeclaration.model_validate(declaration))
    refs = tuple(
        ReferenceSpec(item.slot_key, TargetKey(item.target_type, "11" if item.target_type == "model" else "7"))
        for item in requests
    )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            sa.insert(App).values(
                id="actual-app",
                tenant_id=101,
                slug="actual",
                name="application",
                owner_user_id=4,
                state="online",
                current_version_id=VERSION,
            )
        )
        for number, version_id in enumerate((VERSION, HISTORY), 1):
            await connection.execute(
                sa.insert(AppVersion).values(
                    id=version_id,
                    app_id="actual-app",
                    version_no=number,
                    kind="initial",
                    terminal_state=None,
                    code_object_key="snapshot",
                    manifest={"capabilities": declaration, "original": " text "},
                    capabilities=declaration,
                    injections={},
                    tier_id="light",
                    runtime="python3.11",
                )
            )
            await connection.execute(
                sa.insert(BusinessReferenceSet).values(
                    tenant_id=101,
                    source_type="hosted_app_version",
                    source_id="actual-app",
                    source_version=version_id,
                    source_revision=1,
                    extractor_version=APP_REFERENCE_EXTRACTOR_VERSION,
                    digest=reference_set_digest(refs),
                    ready=True,
                    effective=True,
                )
            )
            for item in refs:
                await connection.execute(
                    sa.insert(BusinessResourceReference).values(
                        tenant_id=101,
                        source_type="hosted_app_version",
                        source_id="actual-app",
                        source_version=version_id,
                        slot_key=item.slot_key,
                        target_type=item.target.target_type.value,
                        target_id=item.target.target_id,
                        target_tenant_id=101,
                        source_revision=1,
                    )
                )
        await connection.execute(
            sa.insert(BusinessReferenceSet).values(
                tenant_id=101,
                source_type="hosted_app_version",
                source_id="actual-app",
                source_version="__root__",
                record_kind="root_guard",
                source_revision=1,
                extractor_version="root-guard-v1",
                digest=reference_set_digest(()),
                ready=False,
                effective=False,
            )
        )
        await connection.execute(sa.insert(HostedAppSubject).values(id=7, app_id="actual-app"))
        await connection.execute(
            sa.insert(ApiCredential).values(
                id=9,
                tenant_id=101,
                subject_kind="hosted_app",
                subject_id=7,
                name="runtime",
                key_prefix="bs-app-",
                last4="test",
                token_hash="0" * 64,
                scopes=list(identity.scopes),
            )
        )
    auth = AsyncMock()
    pending = AsyncMock(return_value=[])
    monkeypatch.setattr(module, "authorize_loaded_app", auth)
    monkeypatch.setattr(module, "pending_app_reviews", pending)
    monkeypatch.setattr(module, "get_model_name_resolution_port", lambda: names)
    token = set_current_open_api_principal(identity)
    actor_token = set_current_permission_actor(PermissionActor(subject_type="user", subject_id=4, tenant_id=101))
    try:
        yield SimpleNamespace(
            engine=engine, identity=identity, names=names, references=refs, auth=auth, pending=pending
        )
    finally:
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(token)


def request(version=None, purpose="execute"):
    return SourceReadRequest(SourceType.HOSTED_APP_VERSION, "actual-app", version, purpose=purpose)


async def test_actual_uuid_frozen_id_map_and_canonical_original_configuration(application):
    async with AsyncSession(application.engine) as session, session.begin():
        owner = module.HostedAppReferenceSourceOwner()
        snapshot = await owner.aresolve_source(session, request(), application.identity)
        assert snapshot.source_key.source_version == VERSION and snapshot.source_key.tenant_id == 101
        assert snapshot.references == tuple(sorted(application.references, key=lambda item: item.slot_key))
        payload = json.loads(snapshot.payload_json)
        assert payload["manifest"]["original"] == " text "
        assert snapshot.payload_json == canonical_payload_json(payload)
        assert not any(isinstance(row, (App, AppVersion, ApiCredential)) for row in session.identity_map.values())
        assert not session.dirty


@pytest.mark.parametrize("change", ["other_version", "clone", "wrong_app", "revoked", "wrong_subject"])
async def test_runtime_identity_is_current_and_cannot_select_another_version(application, change):
    async with AsyncSession(application.engine) as session, session.begin():
        identity = application.identity
        version = None
        if change == "other_version":
            version = HISTORY
        elif change == "clone":
            identity = identity.model_copy()
        elif change == "wrong_app":
            identity = identity.model_copy(update={"subject_ref": "other"})
        elif change == "revoked":
            from datetime import datetime

            await session.execute(
                sa.update(ApiCredential).where(ApiCredential.id == 9).values(revoked_at=datetime.utcnow())
            )
        else:
            await session.execute(sa.update(HostedAppSubject).where(HostedAppSubject.id == 7).values(app_id="other"))
        with pytest.raises((ResourceReferenceInvalidError, OpenApiCredentialInvalidError)):
            await module.HostedAppReferenceSourceOwner().aresolve_source(session, request(version), identity)


async def test_missing_index_does_not_bootstrap_existing_version(application):
    async with AsyncSession(application.engine) as session, session.begin():
        await session.execute(sa.delete(BusinessReferenceSet).where(BusinessReferenceSet.source_version == VERSION))
        with pytest.raises(ReferenceCoverageNotReadyError):
            await module.HostedAppReferenceSourceOwner().aresolve_source(session, request(), application.identity)


async def test_final_rechecks_credential_in_the_same_session(application):
    from datetime import datetime

    async with AsyncSession(application.engine) as session, session.begin():
        owner = module.HostedAppReferenceSourceOwner()
        snapshot = await owner.aresolve_source(session, request(), application.identity)
        await session.execute(
            sa.update(ApiCredential).where(ApiCredential.id == 9).values(revoked_at=datetime.utcnow())
        )
        with pytest.raises(OpenApiCredentialInvalidError):
            await owner.arevalidate_source(session, request(), application.identity, snapshot)


async def test_inspect_preserves_frozen_missing_target_id_instead_of_resolving_new_name(application):
    from bisheng.llm.domain.models.llm_server import LLMModel

    async with AsyncSession(application.engine) as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11))
        snapshot = await module.HostedAppReferenceSourceOwner().aresolve_source(
            session, request(purpose="inspect"), application.identity
        )
        assert any(item.target.target_id == "11" for item in snapshot.references)


async def test_user_preview_uses_original_qualification_and_pending_task_not_owner_identity(application):
    user = UserPayload(user_id=22, user_name="reviewer", tenant_id=101, user_role=[])
    qualification = PreviewQualification(101, "actual-app", HISTORY, 22, "approval", 1, 2)
    application.pending.return_value = [SimpleNamespace(tenant_id=101, version_id=HISTORY, instance_id=1, task_id=2)]
    token = set_current_open_api_principal(None)
    actor_token = set_current_permission_actor(PermissionActor(subject_type="user", subject_id=22, tenant_id=101))
    try:
        async with AsyncSession(application.engine) as session, session.begin():
            owner = module.HostedAppReferenceSourceOwner(authorization_context=qualification)
            snapshot = await owner.aresolve_source(session, request(HISTORY), user)
            assert snapshot.source_key.source_version == HISTORY
            application.auth.assert_not_awaited()
            assert application.pending.await_args.kwargs["session"] is session
            application.pending.return_value = []
            with pytest.raises(ResourceReferenceInvalidError):
                await owner.arevalidate_source(session, request(HISTORY), user, snapshot)
    finally:
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(token)


async def test_current_user_uses_visibility_and_noncurrent_retains_edit_gate(application, monkeypatch):
    user = UserPayload(user_id=22, user_name="viewer", tenant_id=101, user_role=[])
    visible = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", visible)
    token = set_current_open_api_principal(None)
    actor_token = set_current_permission_actor(PermissionActor(subject_type="user", subject_id=22, tenant_id=101))
    try:
        async with AsyncSession(application.engine) as session, session.begin():
            await module.HostedAppReferenceSourceOwner().aresolve_source(session, request(), user)
            visible.assert_awaited_once_with(user, resource_type="app", resource_id="actual-app", action="visible")
            application.auth.assert_not_awaited()
            await module.HostedAppReferenceSourceOwner().aresolve_source(session, request(HISTORY), user)
            assert application.auth.await_args.args[0] is user
            assert application.auth.await_args.args[2] == "management_preview"
    finally:
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(token)


async def test_original_publish_only_service_account_uses_frozen_operation_without_extra_edit(application):
    original = principal(
        actor_kind="service_account",
        actor_id=77,
        subject_ref=None,
        scopes=frozenset({"app:manage"}),
        authorization_subject_type="service_account",
        authorization_subject_id=77,
    )
    context = {
        "schema": 1,
        "origin_kind": "user_request",
        "mode": "S",
        "purpose": "approved_start",
        "required_actions": ["publish"],
        "actor": {"subject_type": "service_account", "subject_id": 77, "tenant_id": 101},
        "credential_ref": {"kind": "api_credential", "credential_id": 9, "tenant_id": 101},
        "target": {"tenant_id": 101, "app_id": "actual-app", "version_id": HISTORY},
    }
    token = set_current_open_api_principal(original)
    actor_token = set_current_permission_actor(
        PermissionActor(subject_type="service_account", subject_id=77, tenant_id=101)
    )
    try:
        async with AsyncSession(application.engine) as session, session.begin():
            await session.execute(
                sa.update(ApiCredential)
                .where(ApiCredential.id == 9)
                .values(subject_kind="service_account", subject_id=77, scopes=["app:manage"])
            )
            owner = module.HostedAppReferenceSourceOwner(authorization_context=context)
            snapshot = await owner.aresolve_source(session, request(HISTORY), original)
            assert snapshot.source_key.source_version == HISTORY
            assert application.auth.await_args.args[0] is original
            assert application.auth.await_args.args[2] == "approved_start"
            from datetime import datetime

            await session.execute(
                sa.update(ApiCredential).where(ApiCredential.id == 9).values(revoked_at=datetime.utcnow())
            )
            with pytest.raises(OpenApiCredentialInvalidError):
                await owner.arevalidate_source(session, request(HISTORY), original, snapshot)
    finally:
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(token)

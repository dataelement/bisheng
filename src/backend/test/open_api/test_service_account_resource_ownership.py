from types import SimpleNamespace

from bisheng.permission.application.control_state import RuntimeCatalogSnapshot, RuntimeModelSnapshot
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


class State:
    async def current_catalog(self):
        models = (
            RuntimeModelSnapshot(
                snapshot=GrantModelSnapshot("owner", True, ("manage_permission",), 4, True),
                name="Owner",
                kind="STANDARD",
                version=1,
            ),
            RuntimeModelSnapshot(
                snapshot=GrantModelSnapshot("manager", True, ("use", "edit"), 3, True),
                name="Manager",
                kind="STANDARD",
                version=1,
            ),
        )
        return RuntimeCatalogSnapshot(
            release_id=1,
            release_key="current",
            version=1,
            checksum="catalog",
            store_id="store",
            model_id="model",
            model_checksum="checksum",
            models=models,
        )

    async def owner_grant(self, *, target, owner_user_id, source_service, owner_model):
        del owner_user_id, source_service
        return (
            GrantSnapshot(
                grant_id="owner-grant",
                tenant_id=target.tenant_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                model=owner_model,
                active=False,
                sources=(),
            ),
            10,
        )


class Owner:
    def __init__(self):
        self.contexts = []

    async def project_created(self, context):
        self.contexts.append(context)
        return context


def runtime(owner: Owner) -> F048PermissionRuntime:
    return F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=State(),
        marker=SimpleNamespace(),
        decision=SimpleNamespace(),
        projection=SimpleNamespace(),
        sources=GrantSourceService(),
        owner=owner,
        grants=SimpleNamespace(),
        modes=SimpleNamespace(),
        explain=SimpleNamespace(),
    )


def target(*, resource_type="knowledge_library", parent=False):
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=4,
        resource_type=resource_type,
        resource_id="91",
        resource_version=0,
        context_version="created:91",
        parent_type="knowledge_library" if parent else None,
        parent_id="12" if parent else None,
    )


async def test_sa_self_mode_keeps_natural_owner_and_adds_revocable_back_grant():
    owner = Owner()
    await runtime(owner).authorize_created(
        actor=PermissionActor(subject_type="service_account", subject_id=7, tenant_id=4),
        target=target(),
        owner_user_id=22,
        mode="CUSTOM",
    )
    context = owner.contexts[0]
    assert context.owner_user_id == 22
    grant = context.creation_grants[0]
    assert grant.model.model_key == "manager"
    source = grant.sources[0]
    assert (source.subject_type, source.subject_id) == ("service_account", "7")
    assert source.source_type == "CREATOR_GRANT"
    assert source.protected is False


async def test_delegated_user_and_inherited_children_do_not_add_sa_back_grant():
    owner = Owner()
    user_actor = PermissionActor(subject_type="user", subject_id=22, tenant_id=4)
    await runtime(owner).authorize_created(
        actor=user_actor,
        target=target(),
        owner_user_id=22,
        mode="CUSTOM",
    )
    assert owner.contexts[-1].creation_grants == ()

    sa_actor = PermissionActor(subject_type="service_account", subject_id=7, tenant_id=4)
    await runtime(owner).authorize_created(
        actor=sa_actor,
        target=target(resource_type="knowledge_file", parent=True),
        owner_user_id=22,
        mode="INHERIT",
    )
    assert owner.contexts[-1].creation_grants == ()

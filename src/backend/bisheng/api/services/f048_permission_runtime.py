"""API-process composition root for the F048 permission runtime."""

from __future__ import annotations

from dataclasses import dataclass

from bisheng.api.services.f048_application_permission import (
    ApplicationDaoPermissionLoader,
    F048ApplicationPermissionAdapter,
)
from bisheng.channel.domain.services.f048_channel_permission import (
    ChannelDaoPermissionLoader,
    F048ChannelPermissionAdapter,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    F048KnowledgeFilePermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
    KnowledgeFileDaoPermissionLoader,
)
from bisheng.linsight.domain.services.skill_service import (
    configure_linsight_skill_owner_projection,
)
from bisheng.permission.api.dependencies import (
    configure_catalog_api,
    configure_permission_decision_api,
    configure_resource_permission_api,
)
from bisheng.permission.application.access import configure_f048_runtime
from bisheng.permission.application.catalog_api import (
    F048CatalogApi,
    OpenFGACatalogProjector,
    SqlCatalogImpact,
    SqlCatalogState,
)
from bisheng.permission.application.resource_api import (
    F048ResourcePermissionApi,
)
from bisheng.permission.application.resource_authorization import (
    BoundResourceAuthorizationPort,
    PermissionDecisionApplication,
    ResourceAuthorizationRegistry,
)
from bisheng.permission.application.runtime import (
    F048PermissionRuntime,
    F048RuntimeComponents,
    build_f048_permission_runtime,
)
from bisheng.permission.application.sql_runtime import (
    ExternalProjectionScopePort,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.catalog_service import CatalogService
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.telemetry_search.domain.services.f048_dashboard_permission import (
    DashboardDaoPermissionLoader,
    F048DashboardPermissionAdapter,
)
from bisheng.tenant.domain.services.f048_permission_subject import (
    TenantPermissionSubjectDirectory,
)
from bisheng.tool.domain.services.f048_tool_permission import (
    F048ToolPermissionAdapter,
    ToolDaoPermissionLoader,
)


@dataclass(frozen=True, slots=True)
class F048ApiRuntime:
    components: F048RuntimeComponents
    resources: ResourceAuthorizationRegistry
    adapters: dict[str, object]
    catalog: F048CatalogApi


class F048IdentityOwnerProjection:
    """Adapt a business-verified new-row identity to durable creation."""

    def __init__(self, runtime: F048PermissionRuntime) -> None:
        self._runtime = runtime

    async def authorize_created(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        owner_user_id: int,
        resource_version: int,
        context_version: str,
        idempotency_key: str,
    ):
        target = VerifiedPermissionTarget.from_business_service(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            context_version=context_version,
        )
        actor = PermissionActor(
            user_id=owner_user_id,
            current_tenant_id=tenant_id,
        )
        return await self._runtime.authorize_created(
            actor=actor,
            target=target,
            owner_user_id=owner_user_id,
            mode="CUSTOM",
            protected=True,
            idempotency_key=idempotency_key,
        )


async def initialize_f048_api_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> F048ApiRuntime:
    """Build and install the sole API permission composition."""

    components = await build_f048_permission_runtime(
        client,
        external_scopes=external_scopes,
    )
    runtime = components.facade
    state = components.state

    application = F048ApplicationPermissionAdapter(
        loader=ApplicationDaoPermissionLoader(state),
        permission=runtime,
    )
    channel = F048ChannelPermissionAdapter(
        loader=ChannelDaoPermissionLoader(state),
        source_service=GrantSourceService(),
        permission=runtime,
    )
    knowledge_container = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(state),
        source_service=GrantSourceService(),
        permission=runtime,
    )
    knowledge_file = F048KnowledgeFilePermissionAdapter(
        loader=KnowledgeFileDaoPermissionLoader(state),
        permission=runtime,
    )
    tool = F048ToolPermissionAdapter(
        loader=ToolDaoPermissionLoader(state),
        permission=runtime,
    )
    dashboard = F048DashboardPermissionAdapter(
        loader=DashboardDaoPermissionLoader(state),
        permission=runtime,
    )
    adapters: dict[str, object] = {
        "workflow": application,
        "assistant": application,
        "channel": channel,
        "knowledge_space": knowledge_container,
        "knowledge_library": knowledge_container,
        "folder": knowledge_file,
        "knowledge_file": knowledge_file,
        "tool": tool,
        "dashboard": dashboard,
    }
    registry = ResourceAuthorizationRegistry()
    for resource_type in (
        "workflow",
        "assistant",
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
    ):
        registry.register(
            resource_type,
            BoundResourceAuthorizationPort(
                resource_type=resource_type,
                adapter=adapters[resource_type],
            ),
        )
    registry.register("channel", channel)
    registry.register("tool", tool)
    registry.register("dashboard", dashboard)

    decision_api = PermissionDecisionApplication(
        resources=registry,
        permission=runtime,
    )
    resource_api = F048ResourcePermissionApi(
        resources=registry,
        runtime=runtime,
        subjects=TenantPermissionSubjectDirectory(),
    )
    catalog_state = SqlCatalogState()
    catalog_api = F048CatalogApi(
        state=catalog_state,
        service=CatalogService(
            state=catalog_state,
            impact=SqlCatalogImpact(),
            projector=OpenFGACatalogProjector(
                client=client,
                marker=components.marker,
            ),
        ),
    )
    configure_catalog_api(catalog_api)
    configure_permission_decision_api(decision_api)
    configure_resource_permission_api(resource_api)
    configure_f048_runtime(
        runtime,
        resource_adapters=adapters,
        resource_registry=registry,
    )
    configure_linsight_skill_owner_projection(F048IdentityOwnerProjection(runtime))
    return F048ApiRuntime(
        components=components,
        resources=registry,
        adapters=adapters,
        catalog=catalog_api,
    )

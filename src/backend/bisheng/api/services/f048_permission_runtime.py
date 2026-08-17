"""Composition roots for the F048 permission runtime.

Two entries share one business resource composition: ``initialize_f048_api_runtime``
(API process — also installs the HTTP dependency wiring) and
``initialize_f048_worker_runtime`` (Celery / Linsight worker — same resource
registry, no HTTP wiring).
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from bisheng.api.services.f048_application_permission import (
    ApplicationDaoPermissionLoader,
    F048ApplicationPermissionAdapter,
)
from bisheng.app_runtime.domain.services.f048_app_permission import (
    AppDaoPermissionLoader,
    F048AppPermissionAdapter,
)
from bisheng.app_runtime.domain.services.visibility_audit import (
    HostedAppVisibilityAuditListener,
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
from bisheng.permission.application.process_runtime import (
    initialize_f048_background_runtime,
)
from bisheng.permission.application.resource_api import (
    F048ResourcePermissionApi,
    GrantChangeListenerRegistry,
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


def build_f048_resource_composition(
    runtime: F048PermissionRuntime,
) -> tuple[dict[str, object], ResourceAuthorizationRegistry]:
    """Bind every business resource adapter to ``runtime`` and index them.

    Shared by BOTH composition roots (API + background workers). Keeping it in
    one place is the point: it is the piece a process must install before any
    ``check_business_action`` call — i.e. before ToolExecutor initializes a tool,
    which every Linsight/Celery task does.
    """

    application = F048ApplicationPermissionAdapter(
        loader=ApplicationDaoPermissionLoader(runtime),
        permission=runtime,
    )
    channel = F048ChannelPermissionAdapter(
        loader=ChannelDaoPermissionLoader(runtime),
        source_service=GrantSourceService(),
        permission=runtime,
    )
    knowledge_container = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(runtime),
        source_service=GrantSourceService(),
        permission=runtime,
    )
    knowledge_file = F048KnowledgeFilePermissionAdapter(
        loader=KnowledgeFileDaoPermissionLoader(runtime),
        permission=runtime,
    )
    tool = F048ToolPermissionAdapter(
        loader=ToolDaoPermissionLoader(runtime),
        permission=runtime,
    )
    dashboard = F048DashboardPermissionAdapter(
        loader=DashboardDaoPermissionLoader(runtime),
        permission=runtime,
    )
    hosted_app = F048AppPermissionAdapter(
        loader=AppDaoPermissionLoader(runtime),
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
        # F054 hosted applications. Registering here rather than in the API
        # composition alone is the point: Celery and Linsight processes build
        # the same map, and a type missing from it fails at the first
        # check_business_action with RuntimeError("F048 resource registry is
        # not configured") — far from this file.
        "app": hosted_app,
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
    registry.register("app", hosted_app)
    return adapters, registry


async def initialize_f048_api_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> F048ApiRuntime:
    """Build and install the API process's permission composition.

    Sole composition for THIS process; ``initialize_f048_worker_runtime`` is the
    background-process counterpart and shares the same resource registry build.
    """

    components = await build_f048_permission_runtime(
        client,
        external_scopes=external_scopes,
    )
    runtime = components.facade
    adapters, registry = build_f048_resource_composition(runtime)

    decision_api = PermissionDecisionApplication(
        resources=registry,
        permission=runtime,
    )
    grant_listeners = GrantChangeListenerRegistry()
    # F056: registered here rather than through a module import side effect, so
    # that whether the audit hook exists does not depend on router import order.
    # This composition root is also where ``mutate_grants`` itself is built, so
    # the two cannot drift apart: no API runtime, no mutation to observe.
    grant_listeners.register("app", HostedAppVisibilityAuditListener())
    logger.info("registered visibility-change audit hook for resource_type=app")
    resource_api = F048ResourcePermissionApi(
        resources=registry,
        runtime=runtime,
        subjects=TenantPermissionSubjectDirectory(),
        grant_listeners=grant_listeners,
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


async def initialize_f048_worker_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> F048RuntimeComponents:
    """Composition root for background processes (Celery + Linsight worker).

    ``initialize_f048_background_runtime`` alone is NOT enough for a process that
    runs business code: it installs the permission runtime but leaves the resource
    registry unset, so the first ``check_business_action`` raises
    ``RuntimeError("F048 resource registry is not configured")``. That is exactly
    what silently disabled the Linsight code interpreter — ``ToolExecutor``
    ``_ensure_use_permission_async`` -> ``check_business_action`` blew up inside a
    best-effort ``except``, so every task ran without the tool the user had picked
    (and any non-code-interpreter tool selection failed the task outright, since
    ``init_by_tool_ids`` has no such guard).

    Background processes therefore install the same business resource composition
    the API does; only the HTTP dependency wiring (catalog / decision / resource
    APIs) stays API-only.
    """

    components = await initialize_f048_background_runtime(
        client,
        external_scopes=external_scopes,
    )
    runtime = components.facade
    adapters, registry = build_f048_resource_composition(runtime)
    # Re-configure with the resource composition attached. The background call
    # above already installed `runtime`; this call is the same runtime plus the
    # adapters/registry, so it upgrades the process-global rather than swapping it.
    configure_f048_runtime(
        runtime,
        resource_adapters=adapters,
        resource_registry=registry,
    )
    configure_linsight_skill_owner_projection(F048IdentityOwnerProjection(runtime))
    return components

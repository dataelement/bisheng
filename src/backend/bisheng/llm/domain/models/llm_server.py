import logging
from datetime import datetime

from sqlalchemy import CHAR, Column, DateTime, Integer, Text, UniqueConstraint, text, update
from sqlmodel import Field, col, select

from bisheng.common.errcode.llm_tenant import (
    LLMEndpointNotWhitelistedError,
    LLMModelNotAccessibleError,
    LLMModelSharedReadonlyError,
)
from bisheng.common.models.base import SQLModelSerializable
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.utils import wrapper_bisheng_llm_info, wrapper_bisheng_llm_info_async
from bisheng.utils.http_middleware import _check_is_global_super

_LOG = logging.getLogger(__name__)
# Root tenant constant is declared in database.models.tenant; inline here
# to avoid an import cycle (tenant.py depends on models.base which
# bootstraps before ORM table registration).
_ROOT_TENANT_ID = 1


class LLMServerBase(SQLModelSerializable):
    # Uniqueness is scoped to tenant via the composite ``uk_llm_server_
    # tenant_name`` constraint on the concrete LLMServer class — the
    # per-column ``unique=True`` flag was removed so different Children
    # may reuse names like "Azure-GPT-4".
    name: str = Field(default="", index=True, description="Service name")
    description: str | None = Field(default="", sa_column=Column(Text), description="Service Description")
    type: str = Field(sa_column=Column(CHAR(20)), description="Service Provider Type")
    limit_flag: bool = Field(default=False, description="Whether to turn on the daily call limit")
    limit: int = Field(default=0, description="Daily call limit")
    config: dict | None = Field(
        default=None, sa_column=Column(JsonType), description="Service Provider Public Configuration"
    )
    user_id: int = Field(default=0, description="creatorID")
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant isolation (default Root=1)"
        ),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class LLMModelBase(SQLModelSerializable):
    server_id: int | None = Field(default=None, nullable=False, index=True, description="SERVICESID")
    name: str = Field(default="", description="Model Display Name")
    description: str | None = Field(default="", sa_column=Column(Text), description="Model Description")
    model_name: str = Field(default="", description="Model name, parameters used when instantiating components")
    model_type: str = Field(sa_column=Column(CHAR(20)), description="model type")
    config: dict | None = Field(
        default=None, sa_column=Column(JsonType), description="Service Provider Public Configuration"
    )
    status: int = Field(default=2, description="Model status.0Normal1abnormal:, 2: Unknown")
    remark: str | None = Field(default="", sa_column=Column(Text), description="Abnormal reason")
    # When `status` was last decided (config-time probe or a manual verify).
    # Deliberately NOT `update_time`: that one moves on any column change, so a
    # rename would read as "just verified". Null = never probed.
    status_update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True), description="Last time the model status was checked"
    )
    online: bool = Field(default=True, description="Online")
    user_id: int = Field(default=0, description="creatorID")
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant isolation (mirrors parent llm_server)",
        ),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class LLMServer(LLMServerBase, table=True):
    __tablename__ = "llm_server"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uk_llm_server_tenant_name"),)

    id: int | None = Field(default=None, nullable=False, primary_key=True, description="Service UniqueID")


class LLMModel(LLMModelBase, table=True):
    __tablename__ = "llm_model"
    __table_args__ = (UniqueConstraint("server_id", "model_name", name="server_model_uniq"),)

    id: int | None = Field(default=None, nullable=False, primary_key=True, description="Model UniqueID")


class LLMDao:
    @classmethod
    def get_all_server(cls) -> list[LLMServer]:
        """Get all service providers"""
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_all_server(cls) -> list[LLMServer]:
        """Get all providers asynchronously"""
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def insert_server_with_models(cls, server: LLMServer, models: list[LLMModel]):
        """Insert Service Provider and Model"""
        with get_sync_db_session() as session:
            session.add(server)
            session.flush()
            for model in models:
                model.server_id = server.id
            session.add_all(models)
            session.commit()
            session.refresh(server)
            return server

    @classmethod
    async def _assert_root_writable(cls, server_id: int, operator) -> LLMServer | None:
        """Read server under bypass (so Child-scoped super admins see
        Root rows) and forbid non-super callers from writing to Root-
        owned servers. Returns the existing row or None when absent.

        Non-Root rows pass through unchanged; caller uses the returned
        row to distinguish "absent" from "forbidden" in the delete path.
        """
        with bypass_tenant_filter():
            existing = await cls.aget_server_by_id(server_id)
        if existing is not None and existing.tenant_id == _ROOT_TENANT_ID:
            if not await _check_is_global_super(operator.user_id):
                raise LLMModelSharedReadonlyError.http_exception()
        return existing

    @classmethod
    async def ainsert_server_with_models(
        cls,
        server: LLMServer,
        models: list[LLMModel],
        *,
        share_to_children: bool = True,
        operator=None,
    ):
        """Insert a server + its models. When ``operator`` is set the
        tenant-tree guards apply: tenant_id auto-fill from the current
        scope, endpoint-whitelist enforcement for non-super callers, and
        Root→Children FGA fanout when ``share_to_children`` is true and
        the owning tenant opts in via ``share_default_to_children``.

        ``operator=None`` keeps the v2.5.0 call signature functional for
        tests and legacy callers (no whitelist, no fanout).
        """
        tid = get_current_tenant_id() or _ROOT_TENANT_ID
        server.tenant_id = tid
        for model in models:
            model.tenant_id = tid

        if operator is not None:
            whitelist = getattr(settings.llm, "endpoint_whitelist", []) or []
            if whitelist and not await _check_is_global_super(operator.user_id):
                cfg = server.config or {}
                endpoint = cfg.get("openai_api_base") or cfg.get("endpoint") or ""
                if not any(endpoint.startswith(prefix) for prefix in whitelist):
                    raise LLMEndpointNotWhitelistedError.http_exception()

        async with get_async_db_session() as session:
            session.add(server)
            await session.flush()
            for model in models:
                model.server_id = server.id
            session.add_all(models)
            if models and settings.dsh.enabled:
                from bisheng.dsh.domain.repositories.new_model_visibility import initialize_new_model_visibility

                await initialize_new_model_visibility(session, models, server.user_id)
            await session.commit()
            await session.refresh(server)

        if operator is not None and share_to_children and server.tenant_id == _ROOT_TENANT_ID:
            from bisheng.tenant.domain.services.resource_share_service import (
                ResourceShareService,
            )

            # ``tenant.share_default_to_children`` only governs other resource
            # types (workflow / channel / mount). LLM is solely controlled by
            # the per-request ``share_to_children`` flag — the ModelConfig UI
            # is the source of truth for super admins.
            try:
                await ResourceShareService.enable_sharing(
                    "llm_server",
                    str(server.id),
                    operator=operator,
                )
            except Exception:
                _LOG.exception("enable_sharing llm_server=%s failed", server.id)

        return server

    @classmethod
    async def aupdate_server_share(cls, server_id: int, share_to_children: bool, operator):
        """Toggle Root→Child sharing. Only super admins may flip, only
        Root-owned servers participate. Mirrors the Router-layer guard
        so DAO stays safe even if called directly.
        """
        from bisheng.tenant.domain.services.resource_share_service import (
            ResourceShareService,
        )

        with bypass_tenant_filter():
            server = await cls.aget_server_by_id(server_id)
        if server is None or server.tenant_id != _ROOT_TENANT_ID:
            raise LLMModelNotAccessibleError.http_exception()
        if not await _check_is_global_super(operator.user_id):
            raise LLMModelSharedReadonlyError.http_exception()

        if share_to_children:
            await ResourceShareService.enable_sharing("llm_server", str(server_id), operator=operator)
        else:
            await ResourceShareService.disable_sharing("llm_server", str(server_id), operator=operator)

    @classmethod
    async def update_server_with_models(
        cls,
        server: LLMServer,
        models: list[LLMModel],
        *,
        operator=None,
    ):
        """Update service providers and models. With ``operator`` supplied,
        Root-owned rows are read-only for non-super callers (19801)."""
        if operator is not None and getattr(server, "id", None):
            await cls._assert_root_writable(server.id, operator)

        from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
        from bisheng.llm.domain.repositories.model_deletion_repository import ModelDeletionRepository
        from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository

        async with get_async_db_session() as session:
            await session.begin()
            providers = ModelProviderOperationRepository()
            current = await providers.alock_provider(session, server_id=server.id)
            await providers.arequire_idle(session, server_id=server.id)
            retained = tuple(model.id for model in models if model.id)
            snapshot = await ModelDeletionRepository().alock_removal_targets(
                session, server_id=server.id, retained_model_ids=retained
            )
            if set(snapshot.all_model_ids) != set(retained):
                raise ResourceReferenceInvalidError(reason="model_removal_requires_owner_application")
            if server.tenant_id != current.tenant_id:
                raise LLMModelNotAccessibleError.http_exception()
            for field in ("name", "description", "type", "limit_flag", "limit", "config"):
                setattr(current, field, getattr(server, field))

            add_models = []
            update_models = []
            for model in models:
                if model.id:
                    update_models.append(model)
                else:
                    model.id = None
                    model.server_id = current.id
                    add_models.append(model)
            # New models inherit their provider's owning tenant.
            for model in add_models:
                model.tenant_id = server.tenant_id
            session.add_all(add_models)
            if add_models and settings.dsh.enabled:
                from bisheng.dsh.domain.repositories.new_model_visibility import initialize_new_model_visibility

                await initialize_new_model_visibility(
                    session, add_models, operator.user_id if operator else server.user_id
                )
            # Update data for existing models
            for one in update_models:
                await session.exec(
                    update(LLMModel)
                    .where(
                        LLMModel.id == one.id, LLMModel.server_id == current.id, LLMModel.tenant_id == current.tenant_id
                    )
                    .values(
                        name=one.name,
                        description=one.description,
                        model_name=one.model_name,
                        model_type=one.model_type,
                        config=one.config,
                    )
                )

            await session.commit()
            await session.refresh(current)
            return current

    @classmethod
    def get_all_model(cls) -> list[LLMModel]:
        """Get all models"""
        statement = select(LLMModel)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    @wrapper_bisheng_llm_info(key_prefix="llm:server:")
    def get_server_by_id(cls, server_id: int, *, cache: bool = False) -> LLMServer | None:
        """According to serviceIDGet Service Providers"""
        statement = select(LLMServer).where(LLMServer.id == server_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    @wrapper_bisheng_llm_info_async(key_prefix="llm:server:")
    async def aget_server_by_id(cls, server_id: int, *, cache: bool = False) -> LLMServer | None:
        """According to serviceIDGet Service Providers"""
        statement = select(LLMServer).where(LLMServer.id == server_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_server_by_ids(cls, server_ids: list[int]) -> list[LLMServer]:
        """According to serviceIDGet Service Providers"""
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_server_by_ids(cls, server_ids: list[int]) -> list[LLMServer]:
        """According to serviceIDGet Service Providers"""
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_server_by_name(cls, server_name: str) -> LLMServer | None:
        """Get Service Provider by Service Name"""
        statement = select(LLMServer).where(LLMServer.name == server_name)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_server_by_name(cls, server_name: str) -> LLMServer | None:
        """Get Service Provider by Service Name"""
        statement = select(LLMServer).where(LLMServer.name == server_name)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    @wrapper_bisheng_llm_info(key_prefix="llm:model:")
    def get_model_by_id(cls, model_id: int, *, cache: bool = False) -> LLMModel | None:
        """According to the modelIDGrabbed Objects"""
        # get from cache
        statement = select(LLMModel).where(LLMModel.id == model_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    @wrapper_bisheng_llm_info_async(key_prefix="llm:model:")
    async def aget_model_by_id(cls, model_id: int, *, cache: bool = False) -> LLMModel | None:
        """According to the modelIDGrabbed Objects"""
        statement = select(LLMModel).where(LLMModel.id == model_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_ids(cls, model_ids: list[int]) -> list[LLMModel]:
        """According to the modelIDGrabbed Objects"""
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_ids(cls, model_ids: list[int]) -> list[LLMModel]:
        """According to the modelIDGrabbed Objects"""
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_model_by_type(cls, model_type: LLMModelType) -> LLMModel | None:
        """Get first created model based on model type"""
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(col(LLMModel.id).asc())
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_model_by_type(cls, model_type: LLMModelType) -> LLMModel | None:
        """Get first created model based on model type"""
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(col(LLMModel.id).asc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_server_ids(cls, server_ids: list[int]) -> list[LLMModel]:
        """According to serviceIDGrabbed Objects"""
        statement = (
            select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(col(LLMModel.update_time).desc())
        )
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_server_ids(cls, server_ids: list[int]) -> list[LLMModel]:
        """According to serviceIDGet the first model created"""
        statement = (
            select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(col(LLMModel.update_time).desc())
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def update_model_status(cls, model_id: int, status: int, remark: str = ""):
        """Update model status and stamp when it was decided."""
        from bisheng.llm.domain.repositories.model_provider_write_guard import check_idle_model_write, lock_idle_model

        with get_sync_db_session() as session:
            session.begin()
            tenant, server_id, transaction = lock_idle_model(session, model_id)
            session.exec(
                update(LLMModel)
                .where(LLMModel.id == model_id, LLMModel.tenant_id == tenant, LLMModel.server_id == server_id)
                .values(status=status, remark=remark, status_update_time=datetime.now())
            )
            check_idle_model_write(session, tenant, transaction)
            session.commit()

    @classmethod
    async def aupdate_model_status(cls, model_id: int, status: int, remark: str = ""):
        """Asynchronously update model status and stamp when it was decided."""
        from bisheng.llm.domain.repositories.model_provider_write_guard import alock_idle_model, check_idle_model_write

        async with get_async_db_session() as session:
            await session.begin()
            tenant, server_id, transaction = await alock_idle_model(session, model_id)
            await session.exec(
                update(LLMModel)
                .where(LLMModel.id == model_id, LLMModel.tenant_id == tenant, LLMModel.server_id == server_id)
                .values(status=status, remark=remark, status_update_time=datetime.now())
            )
            check_idle_model_write(session, tenant, transaction)
            await session.commit()

    @classmethod
    def update_model_online(cls, model_id: int, online: bool):
        """Update model online status"""
        from bisheng.llm.domain.repositories.model_provider_write_guard import check_idle_model_write, lock_idle_model

        with get_sync_db_session() as session:
            session.begin()
            tenant, server_id, transaction = lock_idle_model(session, model_id)
            session.exec(
                update(LLMModel)
                .where(LLMModel.id == model_id, LLMModel.tenant_id == tenant, LLMModel.server_id == server_id)
                .values(online=online)
            )
            check_idle_model_write(session, tenant, transaction)
            session.commit()

    @classmethod
    async def aupdate_model_online(cls, model_id: int, online: bool):
        """Asynchronous update model online status"""
        from bisheng.llm.domain.repositories.model_provider_write_guard import alock_idle_model, check_idle_model_write

        async with get_async_db_session() as session:
            await session.begin()
            tenant, server_id, transaction = await alock_idle_model(session, model_id)
            await session.exec(
                update(LLMModel)
                .where(LLMModel.id == model_id, LLMModel.tenant_id == tenant, LLMModel.server_id == server_id)
                .values(online=online)
            )
            check_idle_model_write(session, tenant, transaction)
            await session.commit()

    @classmethod
    async def adelete_server_by_id(cls, server_id: int, *, operator=None):
        """Legacy callers must enter the same real Owner confirmation flow."""
        if operator is None:
            raise LLMModelNotAccessibleError.http_exception()
        existing = await cls._assert_root_writable(server_id, operator)
        if existing is None:
            raise LLMModelNotAccessibleError.http_exception()
        from bisheng.llm.application.model_deletion import get_model_deletion_application

        application = await get_model_deletion_application()
        return await application.adelete_server(identity=operator, server_id=server_id)

    @classmethod
    async def aget_shared_server_ids_for_leaf(cls, leaf_id: int, *, raise_on_error: bool = False) -> list[int]:
        """Return Root LLM server IDs shared to the given leaf.

        Returns [] for Root callers, and — by default — also when permissions
        are unavailable: for the management list that only means a Child sees
        fewer Root-shared providers for a moment.

        ``raise_on_error=True`` is for callers where swallowing the failure is a
        silent narrowing that then reads as a configuration error to whoever hit
        it. The model protocol face passes it so an FGA blip answers "cannot
        determine the callable range" (503) instead of "that model does not
        exist" (404).
        """
        from bisheng.permission.application import PermissionSubject, get_permission_relation_api

        if leaf_id == _ROOT_TENANT_ID:
            return []
        try:
            permissions = await get_permission_relation_api()
            objects = await permissions.list_resource_ids(
                subject=PermissionSubject("tenant", str(leaf_id)),
                relation="shared_with",
                resource_type="llm_server",
            )
        except Exception:
            _LOG.exception("Permission resource lookup for leaf=%s failed", leaf_id)
            if raise_on_error:
                raise
            return []

        result: list[int] = []
        for resource_id in objects:
            if resource_id.isdigit():
                result.append(int(resource_id))
        return result

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import CHAR, JSON, Column, DateTime, Text, UniqueConstraint, delete, text, update
from sqlmodel import Field, select, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.utils import wrapper_bisheng_llm_info, wrapper_bisheng_llm_info_async


class LLMServerBase(SQLModelSerializable):
    # F020: name uniqueness scoped to tenant via the composite
    # ``uk_llm_server_tenant_name`` UniqueConstraint on the concrete
    # LLMServer class below; the per-column ``unique=True`` flag was
    # removed so different Children may reuse names like "Azure-GPT-4".
    name: str = Field(default='', index=True, description='Service name')
    description: Optional[str] = Field(default='', sa_column=Column(Text), description='Service Description')
    type: str = Field(sa_column=Column(CHAR(20)), description='Service Provider Type')
    limit_flag: bool = Field(default=False, description='Whether to turn on the daily call limit')
    limit: int = Field(default=0, description='Daily call limit')
    config: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                   description='Service Provider Public Configuration')
    user_id: int = Field(default=0, description='creatorID')
    # F001 (v2.5.0) added this column at the DB level with server_default=1;
    # the ORM field was never declared, causing the tenant_filter event to
    # skip llm_server writes. F020 surfaces it so auto-fill (get_current_
    # tenant_id) and the composite unique key can function.
    tenant_id: int = Field(default=1, index=True, nullable=False,
                           description='F001: Tenant isolation (default Root=1)')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LLMModelBase(SQLModelSerializable):
    server_id: Optional[int] = Field(default=None, nullable=False, index=True, description='SERVICESID')
    name: str = Field(default='', description='Model Display Name')
    description: Optional[str] = Field(default='', sa_column=Column(Text), description='Model Description')
    model_name: str = Field(default='', description='Model name, parameters used when instantiating components')
    model_type: str = Field(sa_column=Column(CHAR(20)), description='model type')
    config: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                   description='Service Provider Public Configuration')
    status: int = Field(default=2, description='Model status.0Normal1abnormal:, 2: Unknown')
    remark: Optional[str] = Field(default='', sa_column=Column(Text), description='Abnormal reason')
    online: bool = Field(default=True, description='Online')
    user_id: int = Field(default=0, description='creatorID')
    # F001 (v2.5.0) added the column; F020 surfaces it on the ORM. Kept
    # aligned with the parent llm_server so cascading ORM inserts fill both.
    tenant_id: int = Field(default=1, index=True, nullable=False,
                           description='F001: Tenant isolation (mirrors parent llm_server)')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LLMServer(LLMServerBase, table=True):
    __tablename__ = 'llm_server'
    __table_args__ = (
        # F020: replaces the v2.4 UNIQUE(name) global constraint.
        UniqueConstraint('tenant_id', 'name', name='uk_llm_server_tenant_name'),
    )

    id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='Service UniqueID')


class LLMModel(LLMModelBase, table=True):
    __tablename__ = 'llm_model'
    __table_args__ = (UniqueConstraint('server_id', 'model_name', name='server_model_uniq'),)

    id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='Model UniqueID')


class LLMDao:

    @classmethod
    def get_all_server(cls) -> List[LLMServer]:
        """ Get all service providers """
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_all_server(cls) -> List[LLMServer]:
        """ Get all providers asynchronously """
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def insert_server_with_models(cls, server: LLMServer, models: List[LLMModel]):
        """ Insert Service Provider and Model """
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
    async def ainsert_server_with_models(
        cls,
        server: LLMServer,
        models: List[LLMModel],
        *,
        share_to_children: bool = True,
        operator=None,
    ):
        """Insert service providers and models asynchronously.

        F020 extensions (active when Service layer (T07) passes ``operator``):

        1. Fill ``tenant_id`` on ``server`` and each model from
           ``get_current_tenant_id()`` — honours the F019 admin-scope override
           so a super admin switched to Child 5 writes new LLMs under
           ``tenant_id=5``.
        2. If ``llm.endpoint_whitelist`` is configured and the caller is
           not a global super admin, ``config.openai_api_base`` /
           ``config.endpoint`` must match one of the whitelisted prefixes
           (19804). Empty whitelist means no restriction.
        3. When the resulting server lands on Root (tenant_id=1),
           ``share_to_children`` is true, and ``Tenant.share_default_to_children``
           is enabled, fan out ``{llm_server:id}#shared_with → tenant:{child}``
           tuples to every active Child via F017 ResourceShareService
           (AC-01, INV-T15).

        ``operator=None`` keeps the v2.5.0 call signature functional for
        tests and legacy callers: no whitelist check, no FGA fanout —
        same behaviour as before F020.
        """
        from bisheng.core.context.tenant import get_current_tenant_id

        tid = get_current_tenant_id() or 1
        server.tenant_id = tid
        for model in models:
            model.tenant_id = tid

        # F020 D6: endpoint whitelist guard.
        if operator is not None:
            from bisheng.common.services.config_service import settings
            from bisheng.common.errcode.llm_tenant import LLMEndpointNotWhitelistedError
            from bisheng.utils.http_middleware import _check_is_global_super

            whitelist = getattr(settings.llm, 'endpoint_whitelist', []) or []
            if whitelist and not await _check_is_global_super(operator.user_id):
                cfg = server.config or {}
                endpoint = cfg.get('openai_api_base') or cfg.get('endpoint') or ''
                if not any(endpoint.startswith(prefix) for prefix in whitelist):
                    raise LLMEndpointNotWhitelistedError.http_exception()

        async with get_async_db_session() as session:
            session.add(server)
            await session.flush()
            for model in models:
                model.server_id = server.id
            session.add_all(models)
            await session.commit()
            await session.refresh(server)

        # F020 D2: Root → Children fanout (AC-01). Non-Root tenants and the
        # share_to_children=False branch (AC-02) skip this unconditionally.
        if operator is not None and share_to_children and server.tenant_id == 1:
            from bisheng.database.models.tenant import TenantDao
            from bisheng.tenant.domain.services.resource_share_service import (
                ResourceShareService,
            )

            tenant = await TenantDao.aget(server.tenant_id)
            if tenant is not None and getattr(tenant, 'share_default_to_children', False):
                try:
                    await ResourceShareService.enable_sharing(
                        'llm_server', str(server.id),
                    )
                except Exception:  # noqa: BLE001 — FGA failure must not block local write
                    import logging
                    logging.getLogger(__name__).exception(
                        '[F020] enable_sharing llm_server=%s failed', server.id,
                    )

        return server

    @classmethod
    async def aupdate_server_share(cls, server_id: int, share_to_children: bool, operator):
        """F020 AC-04: toggle Root→Child sharing on an existing llm_server.

        Only Root (tenant_id=1) servers participate in group sharing, and
        only the global super admin may flip the switch — enforcement
        mirrors the Router-layer check. Uses F017 ResourceShareService so
        the DSL v2.0.1 tuple shape (``shared_with`` per-Child fanout)
        stays in one place.

        Reads under ``bypass_tenant_filter`` because the caller may be a
        super admin operating from a Child scope (F019); the event-layer
        IN-list filter would otherwise hide Root servers.
        """
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.utils.http_middleware import _check_is_global_super
        from bisheng.common.errcode.llm_tenant import (
            LLMModelNotAccessibleError,
            LLMModelSharedReadonlyError,
        )

        with bypass_tenant_filter():
            server = await cls.aget_server_by_id(server_id)
        if server is None or server.tenant_id != 1:
            raise LLMModelNotAccessibleError.http_exception()
        if not await _check_is_global_super(operator.user_id):
            raise LLMModelSharedReadonlyError.http_exception()

        from bisheng.tenant.domain.services.resource_share_service import (
            ResourceShareService,
        )
        if share_to_children:
            await ResourceShareService.enable_sharing('llm_server', str(server_id))
        else:
            await ResourceShareService.disable_sharing('llm_server', str(server_id))

    @classmethod
    async def update_server_with_models(
        cls,
        server: LLMServer,
        models: List[LLMModel],
        *,
        operator=None,
    ):
        """Update service providers and models.

        F020: when ``operator`` is supplied (T07 Service onwards), a
        server already owned by Root (tenant_id=1) is read-only for
        non-super callers (19801). Same-tenant edits and super admin
        edits proceed unchanged.

        The existing row is read under ``bypass_tenant_filter`` because
        a Child-scoped super admin (F019) would otherwise not see it.
        """
        if operator is not None and getattr(server, 'id', None):
            from bisheng.core.context.tenant import bypass_tenant_filter
            from bisheng.utils.http_middleware import _check_is_global_super
            from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError

            with bypass_tenant_filter():
                existing = await cls.aget_server_by_id(server.id)
            if existing is not None and existing.tenant_id == 1:
                if not await _check_is_global_super(operator.user_id):
                    raise LLMModelSharedReadonlyError.http_exception()

        async with get_async_db_session() as session:
            session.add(server)

            add_models = []
            update_models = []
            for model in models:
                if model.id:
                    update_models.append(model)
                else:
                    add_models.append(model)
            # Delete model
            await session.exec(
                delete(LLMModel).where(col(LLMModel.server_id) == server.id,
                                       col(LLMModel.id).not_in([model.id for model in update_models])))
            # Add New Model
            session.add_all(add_models)
            # Update data for existing models
            for one in update_models:
                await session.exec(
                    update(LLMModel).where(LLMModel.id == one.id).values(
                        name=one.name,
                        description=one.description,
                        model_name=one.model_name,
                        model_type=one.model_type,
                        config=one.config))

            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    def get_all_model(cls) -> List[LLMModel]:
        """ Get all models """
        statement = select(LLMModel)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    @wrapper_bisheng_llm_info(key_prefix="llm:server:")
    def get_server_by_id(cls, server_id: int, *, cache: bool = False) -> Optional[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    @wrapper_bisheng_llm_info_async(key_prefix="llm:server:")
    async def aget_server_by_id(cls, server_id: int, *, cache: bool = False) -> Optional[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_server_by_ids(cls, server_ids: List[int]) -> List[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_server_by_ids(cls, server_ids: List[int]) -> List[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_server_by_name(cls, server_name: str) -> Optional[LLMServer]:
        """ Get Service Provider by Service Name """
        statement = select(LLMServer).where(LLMServer.name == server_name)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_server_by_name(cls, server_name: str) -> Optional[LLMServer]:
        """ Get Service Provider by Service Name """
        statement = select(LLMServer).where(LLMServer.name == server_name)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    @wrapper_bisheng_llm_info(key_prefix="llm:model:")
    def get_model_by_id(cls, model_id: int, *, cache: bool = False) -> Optional[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        # get from cache
        statement = select(LLMModel).where(LLMModel.id == model_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    @wrapper_bisheng_llm_info_async(key_prefix="llm:model:")
    async def aget_model_by_id(cls, model_id: int, *, cache: bool = False) -> Optional[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_ids(cls, model_ids: List[int]) -> List[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_ids(cls, model_ids: List[int]) -> List[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_model_by_type(cls, model_type: LLMModelType) -> Optional[LLMModel]:
        """ Get first created model based on model type """
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(
            col(LLMModel.id).asc())
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_model_by_type(cls, model_type: LLMModelType) -> Optional[LLMModel]:
        """ Get first created model based on model type """
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(
            col(LLMModel.id).asc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ According to serviceIDGrabbed Objects """
        statement = select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(
            col(LLMModel.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ According to serviceIDGet the first model created """
        statement = select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(
            col(LLMModel.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def update_model_status(cls, model_id: int, status: int, remark: str = ''):
        """ Update model status """
        with get_sync_db_session() as session:
            session.exec(
                update(LLMModel).where(col(LLMModel.id) == model_id).values(status=status,
                                                                            remark=remark))
            session.commit()

    @classmethod
    async def aupdate_model_status(cls, model_id: int, status: int, remark: str = ''):
        """ Asynchronously update model status """
        async with get_async_db_session() as session:
            await session.exec(
                update(LLMModel).where(col(LLMModel.id) == model_id).values(status=status,
                                                                            remark=remark))
            await session.commit()

    @classmethod
    def update_model_online(cls, model_id: int, online: bool):
        """ Update model online status """
        with get_sync_db_session() as session:
            session.exec(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
            session.commit()

    @classmethod
    async def aupdate_model_online(cls, model_id: int, online: bool):
        """ Asynchronous update model online status """
        async with get_async_db_session() as session:
            await session.exec(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
            await session.commit()

    @classmethod
    def delete_server_by_id(cls, server_id: int):
        """ According to serviceIDDelete Service Provider """
        with get_sync_db_session() as session:
            session.exec(delete(LLMServer).where(col(LLMServer.id) == server_id))
            session.exec(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
            session.commit()

    @classmethod
    async def adelete_server_by_id(cls, server_id: int, *, operator=None):
        """Delete a server and cascade its models.

        F020: when ``operator`` is supplied, the Root read-only rule
        (19801) is enforced before any row is touched; a missing server
        raises 19802 so callers can distinguish "unknown id" from
        "forbidden". The FGA ``shared_with`` fanout (if any) is revoked
        unconditionally and idempotently — safe even for servers that
        were never shared. FGA failure is logged but does not abort the
        local delete (aligning with ainsert_server_with_models).
        """
        if operator is not None:
            from bisheng.core.context.tenant import bypass_tenant_filter
            from bisheng.utils.http_middleware import _check_is_global_super
            from bisheng.common.errcode.llm_tenant import (
                LLMModelNotAccessibleError,
                LLMModelSharedReadonlyError,
            )

            with bypass_tenant_filter():
                existing = await cls.aget_server_by_id(server_id)
            if existing is None:
                raise LLMModelNotAccessibleError.http_exception()
            if existing.tenant_id == 1 and not await _check_is_global_super(operator.user_id):
                raise LLMModelSharedReadonlyError.http_exception()

        # F020: idempotent FGA cleanup. Skipped only when ResourceShareService
        # unavailable during early boot (OpenFGA disabled); errors are logged.
        try:
            from bisheng.tenant.domain.services.resource_share_service import (
                ResourceShareService,
            )
            await ResourceShareService.disable_sharing('llm_server', str(server_id))
        except Exception:  # noqa: BLE001 — FGA failure must not block delete
            import logging
            logging.getLogger(__name__).exception(
                '[F020] disable_sharing on delete llm_server=%s failed', server_id,
            )

        async with get_async_db_session() as session:
            await session.exec(delete(LLMServer).where(col(LLMServer.id) == server_id))
            await session.exec(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
            await session.commit()

    @classmethod
    def delete_model_by_ids(cls, model_ids: List[int]):
        """ According to the modelIDDelete model """
        with get_sync_db_session() as session:
            session.exec(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            session.commit()

    @classmethod
    async def adelete_model_by_ids(cls, model_ids: List[int]):
        """ According to the modelIDDelete model """
        async with get_async_db_session() as session:
            await session.exec(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            await session.commit()

    @classmethod
    async def aget_shared_server_ids_for_leaf(cls, leaf_id: int) -> List[int]:
        """F020 T06: return Root llm_server ids shared to the given leaf tenant.

        Reads ``{llm_server}#shared_with → tenant:{leaf}`` tuples via
        OpenFGA ``list_objects`` — this is the read side of the F017
        ``ResourceShareService.enable_sharing`` fanout. Used by T07's
        merged-list query to surface Root-owned, share-enabled models to
        Child users without relying on the SQLAlchemy event layer (which
        still does strict ``tenant_id = current`` filtering and would
        hide Root rows from a Child-scoped session).

        Returns an empty list when:
          - leaf equals Root (no tenant shares to itself);
          - OpenFGA is disabled / unreachable (fail-closed).
        """
        from bisheng.database.models.tenant import ROOT_TENANT_ID
        from bisheng.core.openfga.manager import aget_fga_client

        if leaf_id == ROOT_TENANT_ID:
            return []
        fga = await aget_fga_client()
        if fga is None:
            return []
        try:
            objects = await fga.list_objects(
                user=f'tenant:{leaf_id}',
                relation='shared_with',
                type='llm_server',
            )
        except Exception:  # noqa: BLE001 — read-path: degrade to empty list on FGA failure
            import logging
            logging.getLogger(__name__).exception(
                '[F020] list_objects for leaf=%s failed', leaf_id,
            )
            return []

        result: List[int] = []
        for obj in objects:
            # ``list_objects`` returns ``["llm_server:123", ...]``; tolerate
            # either the prefixed or bare form to be robust against future
            # FGAClient format changes.
            _, _, tail = obj.rpartition(':')
            if tail.isdigit():
                result.append(int(tail))
        return result

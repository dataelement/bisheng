"""Workflow persistence participating in an externally owned async transaction.

Binding orchestration takes target locks before alock_root. Version mutations
then use that same live root and Session; this Repository never commits, begins
or rolls back, and never writes reference guards or authorizes callers.
"""

from copy import deepcopy

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.flow import CurVersionDelError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.flow import Flow, FlowType
from bisheng.database.models.flow_version import FlowVersion


class WorkflowVersionRepository:
    @staticmethod
    async def aget_root_by_name(session: AsyncSession, tenant_id: int, user_id: int, name: str) -> Flow | None:
        return await session.scalar(
            select(Flow).where(
                Flow.tenant_id == tenant_id,
                Flow.user_id == user_id,
                Flow.name == name,
                Flow.flow_type == FlowType.WORKFLOW.value,
                Flow.is_delete == 0,
            )
        )

    @staticmethod
    async def aget_root(session: AsyncSession, flow_id: str, tenant_id: int) -> Flow:
        root = await session.scalar(
            select(Flow)
            .where(
                Flow.id == flow_id,
                Flow.tenant_id == tenant_id,
                Flow.flow_type == FlowType.WORKFLOW.value,
                Flow.is_delete == 0,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            raise NotFoundError()
        return root

    @staticmethod
    async def alock_root(session: AsyncSession, flow_id: str, tenant_id: int) -> Flow:
        """Lock the real shared root after binding target locks were acquired."""
        result = await session.execute(
            select(Flow)
            .where(
                Flow.id == flow_id,
                Flow.tenant_id == tenant_id,
                Flow.flow_type == FlowType.WORKFLOW.value,
                Flow.is_delete == 0,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        root = result.scalar_one_or_none()
        if root is None:
            raise NotFoundError()
        return root

    @staticmethod
    def _root(session: AsyncSession, root: Flow) -> None:
        if (
            inspect(root).session is not session.sync_session
            or root.flow_type != FlowType.WORKFLOW.value
            or root.is_delete != 0
            or root.tenant_id is None
            or root.tenant_id <= 0
        ):
            raise ValueError("workflow writes require a live root in the caller's Session")

    @classmethod
    async def aget_version(
        cls,
        session: AsyncSession,
        root: Flow,
        version_id: int,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> FlowVersion:
        cls._root(session, root)
        query = select(FlowVersion).where(
            FlowVersion.id == version_id,
            FlowVersion.flow_id == root.id,
            FlowVersion.tenant_id == root.tenant_id,
        )
        if not include_deleted:
            query = query.where(FlowVersion.is_delete == 0)
        if for_update:
            query = query.with_for_update()
        version = await session.scalar(query.execution_options(populate_existing=True))
        if version is None:
            raise NotFoundError()
        return version

    @classmethod
    async def alist_versions(
        cls, session: AsyncSession, root: Flow, *, include_deleted: bool = False, for_update: bool = False
    ) -> tuple[FlowVersion, ...]:
        cls._root(session, root)
        query = select(FlowVersion).where(FlowVersion.flow_id == root.id, FlowVersion.tenant_id == root.tenant_id)
        if not include_deleted:
            query = query.where(FlowVersion.is_delete == 0)
        if for_update:
            query = query.with_for_update()
        result = await session.scalars(query.order_by(FlowVersion.id).execution_options(populate_existing=True))
        return tuple(result)

    @classmethod
    async def aget_version_by_name(cls, session: AsyncSession, root: Flow, name: str) -> FlowVersion | None:
        cls._root(session, root)
        return await session.scalar(
            select(FlowVersion).where(
                FlowVersion.flow_id == root.id,
                FlowVersion.tenant_id == root.tenant_id,
                FlowVersion.name == name,
                FlowVersion.is_delete == 0,
            )
        )

    @classmethod
    async def acreate_workflow(cls, session: AsyncSession, root: Flow) -> tuple[Flow, FlowVersion]:
        if root.flow_type != FlowType.WORKFLOW.value or root.is_delete != 0 or not root.tenant_id:
            raise ValueError("new workflow requires a live root and its verified tenant")
        session.add(root)
        initial = FlowVersion(
            flow_id=root.id,
            name="v0",
            user_id=root.user_id,
            tenant_id=root.tenant_id,
            flow_type=FlowType.WORKFLOW.value,
            data=deepcopy(root.data),
            is_current=1,
        )
        session.add(initial)
        await session.flush()
        return root, initial

    @classmethod
    async def acreate_version(cls, session: AsyncSession, root: Flow, version: FlowVersion) -> FlowVersion:
        """Flush a genuine new leaf to obtain its ID before binding prepare.

        The caller must still prepare bindings and lock/recheck the existing
        root before committing this leaf. No existing row may be passed here.
        """
        cls._root(session, root)
        if version.id is not None or version.flow_id != root.id or version.tenant_id not in {None, root.tenant_id}:
            raise ValueError("new workflow version must belong to the supplied root")
        version.tenant_id = root.tenant_id
        version.flow_type = FlowType.WORKFLOW.value
        version.is_current = 0
        version.is_delete = 0
        session.add(version)
        await session.flush()
        return version

    @classmethod
    async def aupdate_version(cls, session: AsyncSession, root: Flow, version: FlowVersion) -> FlowVersion:
        cls._root(session, root)
        if version.flow_id != root.id or version.tenant_id not in {None, root.tenant_id}:
            raise ValueError("workflow version must belong to the supplied root")
        # Snapshot detached/request changes before populate_existing reloads
        # the tracked SQL row. Only the established mutable fields are copied.
        changes = {key: deepcopy(getattr(version, key)) for key in ("name", "description", "data", "is_delete")}
        current = await cls.aget_version(session, root, version.id, include_deleted=True, for_update=True)
        for key, value in changes.items():
            setattr(current, key, value)
        if current.is_current == 1:
            root.data = deepcopy(current.data)
        await session.flush()
        return current

    @classmethod
    async def aswitch_current(cls, session: AsyncSession, root: Flow, version_id: int) -> FlowVersion:
        selected = await cls.aget_version(session, root, version_id, for_update=True)
        for version in await cls.alist_versions(session, root, include_deleted=True, for_update=True):
            version.is_current = int(version.id == selected.id)
        root.data = deepcopy(selected.data)
        await session.flush()
        return selected

    @classmethod
    async def asoft_delete_version(cls, session: AsyncSession, root: Flow, version_id: int) -> FlowVersion:
        version = await cls.aget_version(session, root, version_id, for_update=True)
        if version.is_current == 1:
            raise CurVersionDelError()
        version.is_delete = 1
        await session.flush()
        return version

    @classmethod
    async def asoft_delete_workflow(cls, session: AsyncSession, root: Flow) -> tuple[FlowVersion, ...]:
        versions = await cls.alist_versions(session, root, include_deleted=True, for_update=True)
        for version in versions:
            version.is_delete = 1
        root.is_delete = 1
        await session.flush()
        return versions

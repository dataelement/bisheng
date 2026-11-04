"""用户 Owner 的外部投影事务。旧栅栏不能写用户或回执。"""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianIdentityUnavailableError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.user.domain.models.external_identity_projection import UserExternalIdentityProjection, projection_now
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole


def digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ExternalShadowIdentity:
    issuer: str
    subject: str
    external_tenant_id: str
    member_id: str
    display_name: str
    active: bool

    @property
    def identity_key(self) -> str:
        return digest(["kunlian", self.issuer, self.external_tenant_id, self.subject])

    @property
    def external_id(self) -> str:
        return "kunlian:" + self.identity_key

    @property
    def raw_identity(self) -> tuple:
        return self.issuer, self.subject, self.external_tenant_id, self.member_id

    @property
    def payload_digest(self) -> str:
        return digest([self.display_name, self.active])


@dataclass(frozen=True)
class ExternalShadowOperation:
    identity_key: str
    operation_id: str
    fence: int
    source_revision: str
    payload_digest: str


@dataclass(frozen=True)
class ExternalShadowReceipt:
    user_id: int
    operation_id: str
    fence: int
    source_revision: str


@dataclass(frozen=True)
class CurrentExternalAccount:
    user_id: int
    user_name: str
    token_version: int
    role_ids: tuple[int, ...]

    @property
    def source(self) -> str:
        return "kunlian"


class UserExternalIdentityProjectionRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    @staticmethod
    def reject_reserved_creation(source: str, external_id: str | None):
        if source.strip().casefold() == "kunlian" or (external_id or "").strip().casefold().startswith("kunlian:"):
            raise KunlianBindingConflictError()

    @staticmethod
    def guard_profile_update(session, changed: User):
        updates = {
            key
            for key in ("source", "external_id", "delete", "disable_source")
            if inspect(changed).attrs[key].history.has_changes()
        }
        # 先保留修改历史。禁止查询的自动 flush 先写入并清空历史。
        with session.no_autoflush:
            current = session.exec(
                select(User.source, User.external_id).where(User.user_id == changed.user_id).with_for_update()
            ).first()
        if current is None:
            return
        if current.source.strip().casefold() == "kunlian" and updates:
            raise KunlianBindingConflictError()
        if updates & {"source", "external_id"}:
            UserExternalIdentityProjectionRepository.reject_reserved_creation(changed.source, changed.external_id)

    @asynccontextmanager
    async def _session(self):
        if get_current_tenant_id() != 1:
            raise KunlianBindingConflictError()
        with strict_tenant_filter():
            async with self.session_factory() as session:
                try:
                    async with session.begin():
                        yield session
                except IntegrityError:
                    raise KunlianBindingConflictError() from None
                except SQLAlchemyError:
                    raise KunlianDependencyUnavailableError() from None

    @staticmethod
    def _validate(identity: ExternalShadowIdentity, source_revision: str):
        lengths = [
            (identity.issuer, 2048),
            (identity.subject, 128),
            (identity.external_tenant_id, 64),
            (identity.member_id, 64),
            (identity.display_name, 128),
        ]
        if (
            any(not isinstance(value, str) or not value or len(value) > size for value, size in lengths)
            or type(identity.active) is not bool
            or not isinstance(source_revision, str)
            or len(source_revision) != 64
            or any(c not in "0123456789abcdef" for c in source_revision)
        ):
            raise KunlianBindingConflictError()

    @staticmethod
    def _check_identity(row, identity):
        if (row.issuer, row.subject, row.external_tenant_id, row.member_id) != identity.raw_identity:
            raise KunlianBindingConflictError()

    async def _state(self, session, identity_key):
        return (
            await session.exec(
                select(UserExternalIdentityProjection)
                .where(UserExternalIdentityProjection.identity_key == identity_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()

    @staticmethod
    def _operation(row) -> ExternalShadowOperation:
        return ExternalShadowOperation(
            row.identity_key, row.operation_id, row.fence, row.source_revision, row.payload_digest
        )

    async def reserve(self, identity: ExternalShadowIdentity, source_revision: str) -> ExternalShadowOperation:
        self._validate(identity, source_revision)
        async with self._session() as session:
            row = await self._state(session, identity.identity_key)
            if row is None:
                row = UserExternalIdentityProjection(
                    identity_key=identity.identity_key,
                    issuer=identity.issuer,
                    subject=identity.subject,
                    external_tenant_id=identity.external_tenant_id,
                    member_id=identity.member_id,
                )
            else:
                self._check_identity(row, identity)
                if (
                    row.source_revision == source_revision
                    and row.payload_digest == identity.payload_digest
                    and row.operation_id is not None
                ):
                    return self._operation(row)
            row.fence += 1
            row.operation_id = str(uuid4())
            row.source_revision = source_revision
            row.payload_digest = identity.payload_digest
            row.update_time = projection_now()
            session.add(row)
            await session.flush()
            return self._operation(row)

    @staticmethod
    def _check_operation(row, operation, revision):
        if (
            row is None
            or (row.identity_key, row.operation_id, row.fence, row.source_revision, row.payload_digest)
            != (operation.identity_key, operation.operation_id, operation.fence, revision, operation.payload_digest)
            or revision != operation.source_revision
        ):
            raise KunlianBindingConflictError()

    async def ensure_shadow(
        self, identity: ExternalShadowIdentity, source_revision: str, *, operation: ExternalShadowOperation
    ) -> int:
        self._validate(identity, source_revision)
        if identity.identity_key != operation.identity_key or identity.payload_digest != operation.payload_digest:
            raise KunlianBindingConflictError()
        async with self._session() as session:
            row = await self._state(session, identity.identity_key)
            self._check_operation(row, operation, source_revision)
            self._check_identity(row, identity)
            if row.user_id is None:
                # 只允许创建。遇到没有本 Owner 回执的现存账号必须拒绝。
                existing = (
                    await session.exec(
                        select(User)
                        .where(User.source == "kunlian", User.external_id == identity.external_id)
                        .with_for_update()
                    )
                ).first()
                if existing is not None:
                    raise KunlianBindingConflictError()
                user = User(
                    user_name=identity.display_name,
                    password="",
                    source="kunlian",
                    external_id=identity.external_id,
                    delete=0 if identity.active else 1,
                    disable_source=None if identity.active else "kunlian",
                )
                session.add(user)
                await session.flush()
                row.user_id = user.user_id
            else:
                user = (await session.exec(select(User).where(User.user_id == row.user_id).with_for_update())).first()
                if user is None or user.source != "kunlian" or user.external_id != identity.external_id:
                    raise KunlianBindingConflictError()
                if (
                    row.applied_operation_id == operation.operation_id
                    and row.applied_fence == operation.fence
                    and row.applied_source_revision == source_revision
                ):
                    return user.user_id
                user.user_name = identity.display_name
                previous_delete = user.delete
                if not identity.active and user.delete == 0:
                    user.delete, user.disable_source = 1, "kunlian"
                elif identity.active and user.delete != 0 and user.disable_source == "kunlian":
                    user.delete, user.disable_source = 0, None
                if previous_delete != user.delete:
                    user.token_version += 1
                user.update_time = projection_now()
                session.add(user)
            row.applied_operation_id = operation.operation_id
            row.applied_fence = operation.fence
            row.applied_source_revision = source_revision
            row.update_time = projection_now()
            session.add(row)
            await session.flush()
            return row.user_id

    async def read_receipt(self, operation: ExternalShadowOperation) -> ExternalShadowReceipt:
        async with self._session() as session:
            row = await self._state(session, operation.identity_key)
            self._check_operation(row, operation, operation.source_revision)
            if (
                row.applied_fence != operation.fence
                or row.applied_operation_id != operation.operation_id
                or row.applied_source_revision != operation.source_revision
                or row.user_id is None
            ):
                raise KunlianBindingConflictError()
            return ExternalShadowReceipt(
                row.user_id, operation.operation_id, operation.fence, operation.source_revision
            )

    async def is_reserved_external_account(self, user_id: int) -> bool:
        async with self._session() as session:
            user = await session.get(User, user_id)
            return bool(
                user
                and (
                    (user.source or "").strip().casefold() == "kunlian"
                    or (user.external_id or "").strip().casefold().startswith("kunlian:")
                )
            )

    async def read_control_plane_actor_roles(self, user_id: int) -> tuple[int, ...]:
        async with self._session() as session:
            user = await session.get(User, user_id)
            if user is None or user.delete != 0:
                raise KunlianIdentityUnavailableError()
            with bypass_tenant_filter():
                roles = (await session.exec(select(UserRole.role_id).where(UserRole.user_id == user_id))).all()
            return tuple(sorted(set(roles)))

    async def read_current_qualification(self, user_id: int, *, identity_key: str) -> CurrentExternalAccount:
        async with self._session() as session:
            state = await session.get(UserExternalIdentityProjection, identity_key)
            user = await session.get(User, user_id)
            if (
                state is None
                or state.user_id != user_id
                or user is None
                or user.source != "kunlian"
                or user.external_id != "kunlian:" + identity_key
                or user.delete != 0
            ):
                raise KunlianIdentityUnavailableError()
            # 与现有登录 Owner 一致。读取该用户全部人工角色。不从外部角色摘要推导。
            with bypass_tenant_filter():
                roles = (await session.exec(select(UserRole.role_id).where(UserRole.user_id == user_id))).all()
            return CurrentExternalAccount(user.user_id, user.user_name, user.token_version, tuple(sorted(set(roles))))

    async def reserve_manual_status(
        self, user_id: int, *, identity_key: str, source_revision: str, disabled: bool, source_active: bool
    ):
        if (
            type(disabled) is not bool
            or type(source_active) is not bool
            or not isinstance(source_revision, str)
            or len(source_revision) != 64
            or any(c not in "0123456789abcdef" for c in source_revision)
        ):
            raise KunlianBindingConflictError()
        async with self._session() as session:
            state = await self._state(session, identity_key)
            if state is None or state.user_id != user_id:
                raise KunlianBindingConflictError()
            payload_digest = digest(["manual", user_id, disabled, source_active])
            if state.source_revision != source_revision or state.payload_digest != payload_digest:
                state.fence += 1
                state.operation_id = str(uuid4())
                state.source_revision = source_revision
                state.payload_digest = payload_digest
                state.update_time = projection_now()
                session.add(state)
                await session.flush()
            return self._operation(state)

    async def set_manual_status(
        self,
        user_id: int,
        *,
        identity_key: str,
        disabled: bool,
        source_active: bool,
        operation: ExternalShadowOperation,
    ):
        if type(disabled) is not bool or type(source_active) is not bool:
            raise KunlianBindingConflictError()
        async with self._session() as session:
            state = await self._state(session, identity_key)
            self._check_operation(state, operation, operation.source_revision)
            if (
                state.user_id != user_id
                or state.identity_key != identity_key
                or operation.payload_digest != digest(["manual", user_id, disabled, source_active])
            ):
                raise KunlianBindingConflictError()
            user = (await session.exec(select(User).where(User.user_id == user_id).with_for_update())).first()
            if user is None or user.source != "kunlian" or user.external_id != "kunlian:" + identity_key:
                raise KunlianBindingConflictError()
            old = user.delete
            if disabled:
                user.delete, user.disable_source = 1, "manual"
            elif source_active:
                user.delete, user.disable_source = 0, None
            else:
                user.delete, user.disable_source = 1, "kunlian"
            if old != user.delete:
                user.token_version += 1
            user.update_time = projection_now()
            session.add(user)
            state.applied_fence = operation.fence
            state.applied_operation_id = operation.operation_id
            state.applied_source_revision = operation.source_revision
            state.update_time = projection_now()
            session.add(state)

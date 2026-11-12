"""昆联目录持久化。每次事务按连接→批次顺序加锁。"""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe

from cryptography.fernet import InvalidToken
from pydantic import SecretStr
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianDirectorySyncError,
    KunlianIdentityUnavailableError,
    KunlianSessionExpiredError,
    KunlianSyncConflictError,
    KunlianTrustRejectedError,
)
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLog
from bisheng.sso_sync.domain.models.kunlian import (
    KunlianConnectionState,
    KunlianDirectoryMember,
    KunlianDirectoryTenant,
    KunlianHandoffReceipt,
    KunlianIdentityBinding,
    KunlianSyncBatch,
    KunlianTenantBinding,
    KunlianWebSession,
    utc_now,
)


@dataclass(frozen=True)
class DirectoryLease:
    connection_id: str
    batch_id: str
    owner: str
    fence: int
    key_version: str
    page_size: int


@dataclass(frozen=True)
class IssuedKunlianSession:
    reference: SecretStr = field(repr=False)
    session_hash: str
    hard_expires_at: datetime
    signing_context: dict = field(repr=False)


@dataclass(frozen=True)
class KunlianAdmissionFacts:
    session: KunlianWebSession = field(repr=False)
    binding: KunlianIdentityBinding = field(repr=False)
    access_token: SecretStr | None = field(default=None, repr=False)
    id_token: SecretStr | None = field(default=None, repr=False)
    mapping: KunlianTenantBinding | None = field(default=None, repr=False)
    published_batch: KunlianSyncBatch | None = field(default=None, repr=False)
    signing_context: dict = field(default_factory=dict, repr=False)
    connection: KunlianConnectionState | None = field(default=None, repr=False)


@dataclass(frozen=True)
class KunlianLogoutMaterial:
    id_token: SecretStr = field(repr=False)
    client_id: str


@dataclass(frozen=True)
class KunlianProjectionFacts:
    identity_key: str
    connection_id: str
    issuer: str
    subject: str
    external_tenant_id: str
    member_id: str
    source_revision: str
    auth_epoch: int
    active: bool
    local_user_id: int | None
    already_projected: bool
    mapping: object
    member_summary: dict = field(repr=False)


@dataclass(frozen=True)
class KunlianLoginFacts:
    binding: KunlianIdentityBinding
    mapping: KunlianTenantBinding | None
    connection: KunlianConnectionState
    published_batch: KunlianSyncBatch | None


@dataclass(frozen=True)
class KunlianOnboardingTenant:
    connection_id: str
    issuer: str
    external_tenant_id: str
    display_name: str
    batch_id: str
    source_revision: str
    policy_revision: int
    max_age_seconds: int
    manual_tenant_id: int | None
    mapping_revision: int | None

    @property
    def source_key(self):
        return KunlianDirectoryRepository._digest(["kunlian", self.issuer, self.external_tenant_id])


class KunlianDirectoryRepository:
    def __init__(
        self,
        session_factory=get_async_db_session,
        *,
        clock=utc_now,
        encrypt_value=None,
        decrypt_value=None,
        key_version=None,
    ):
        self.session_factory = session_factory
        self.clock = clock
        self.encrypt_value = encrypt_value
        self.decrypt_value = decrypt_value
        self.key_version = key_version

    @asynccontextmanager
    async def _session(self):
        # 控制面只允许显式 ROOT 作用域。业务入口必须经受限应用协议。
        if get_current_tenant_id() != 1:
            raise KunlianTrustRejectedError()
        with strict_tenant_filter():
            async with self.session_factory() as session, session.begin():
                yield session

    async def _connection(self, session, connection_id):
        state = (
            await session.exec(
                select(KunlianConnectionState)
                .where(KunlianConnectionState.connection_id == connection_id)
                .with_for_update()
            )
        ).first()
        if state is None:
            raise KunlianDirectoryNotReadyError()
        return state

    async def _locked_lease(self, session, lease, *, statuses=("FETCHING", "VALIDATING")):
        state = await self._connection(session, lease.connection_id)
        now = self.clock()
        if (
            state.sync_fence != lease.fence
            or state.lease_owner != lease.owner
            or state.lease_until is None
            or state.lease_until <= now
        ):
            raise KunlianSyncConflictError()
        batch = (
            await session.exec(
                select(KunlianSyncBatch).where(KunlianSyncBatch.batch_id == lease.batch_id).with_for_update()
            )
        ).first()
        if (
            batch is None
            or batch.connection_id != lease.connection_id
            or batch.fence != lease.fence
            or batch.status not in statuses
            or batch.key_version != lease.key_version
            or batch.page_size != lease.page_size
        ):
            raise KunlianSyncConflictError()
        return state, batch

    async def request_sync(self, connection_id: str) -> int:
        async with self._session() as session:
            state = await self._connection(session, connection_id)
            state.sync_requested_version += 1
            state.sync_requested_at = self.clock()
            state.update_time = self.clock()
            session.add(state)
            return state.sync_requested_version

    def _audit(self, session, *, actor, action, target_id, metadata):
        session.add(
            AuditLog(
                tenant_id=1,
                operator_id=actor.user_id,
                operator_tenant_id=actor.tenant_id,
                action=action,
                target_type="identity_integration",
                target_id=target_id,
                audit_metadata=metadata,
                create_time=self.clock(),
                update_time=self.clock(),
            )
        )

    async def request_manual_sync(self, connection_id: str, *, actor) -> int:
        async with self._session() as session:
            state = await self._connection(session, connection_id)
            if state.sync_requested_version <= state.sync_completed_version:
                state.sync_requested_version += 1
                state.sync_requested_at = state.update_time = self.clock()
                session.add(state)
            self._audit(
                session,
                actor=actor,
                action="kunlian.sync.request",
                target_id=connection_id,
                metadata={"requested_version": state.sync_requested_version},
            )
            return state.sync_requested_version

    async def apply_connection_policy(self, connection_id: str, *, enabled: bool, policy_revision: int) -> int:
        if (
            not isinstance(connection_id, str)
            or not 1 <= len(connection_id) <= 64
            or type(enabled) is not bool
            or type(policy_revision) is not int
            or policy_revision < 1
        ):
            raise KunlianSyncConflictError()
        async with self._session() as session:
            state = (
                await session.exec(
                    select(KunlianConnectionState)
                    .where(KunlianConnectionState.connection_id == connection_id)
                    .with_for_update()
                )
            ).first()
            if state is None:
                state = KunlianConnectionState(
                    connection_id=connection_id,
                    enabled=enabled,
                    policy_revision=policy_revision,
                    sync_requested_version=1,
                    sync_requested_at=self.clock(),
                )
                session.add(state)
                return policy_revision
            if state.policy_revision > policy_revision or (
                state.policy_revision == policy_revision and state.enabled != enabled
            ):
                raise KunlianSyncConflictError()
            if state.policy_revision == policy_revision:
                return policy_revision
            state.policy_revision, state.enabled = policy_revision, enabled
            state.sync_fence += 1
            state.lease_owner, state.lease_until = None, self.clock()
            state.sync_requested_version += 1
            state.sync_requested_at = state.update_time = self.clock()
            batches = (
                await session.exec(
                    select(KunlianSyncBatch)
                    .where(
                        KunlianSyncBatch.connection_id == connection_id,
                        KunlianSyncBatch.status.in_(("FETCHING", "VALIDATING")),
                    )
                    .with_for_update()
                )
            ).all()
            for batch in batches:
                batch.status, batch.reason_code = "ABANDONED", "POLICY_CHANGED"
                batch.completed_at = batch.update_time = self.clock()
                session.add(batch)
            bindings = (
                await session.exec(
                    select(KunlianIdentityBinding)
                    .where(KunlianIdentityBinding.connection_id == connection_id)
                    .order_by(KunlianIdentityBinding.identity_key)
                    .with_for_update()
                )
            ).all()
            for binding in bindings:
                binding.auth_epoch += 1
                binding.update_time = self.clock()
                session.add(binding)
            session.add(state)
            return policy_revision

    async def load_login_facts(
        self, connection_id: str, *, issuer: str, subject: str, external_tenant_id: str
    ) -> KunlianLoginFacts:
        async with self._session() as session:
            connection = await session.get(KunlianConnectionState, connection_id)
            binding = await session.get(KunlianIdentityBinding, self.identity_key(issuer, external_tenant_id, subject))
            if connection is None or binding is None:
                raise KunlianDirectoryNotReadyError()
            if (binding.connection_id, binding.issuer, binding.subject, binding.external_tenant_id) != (
                connection_id,
                issuer,
                subject,
                external_tenant_id,
            ):
                raise KunlianBindingConflictError()
            mapping = await session.get(KunlianTenantBinding, (connection_id, external_tenant_id))
            batch = (
                await session.get(KunlianSyncBatch, connection.active_batch_id) if connection.active_batch_id else None
            )
            return KunlianLoginFacts(binding, mapping, connection, batch)

    async def claim_or_renew_lease(
        self,
        connection_id: str,
        owner: str,
        *,
        key_version: str,
        page_size: int,
        lease: DirectoryLease | None = None,
        ttl_seconds: int = 60,
    ) -> DirectoryLease | None:
        if not owner or len(owner) > 64 or not key_version or len(key_version) > 64:
            raise KunlianSyncConflictError()
        if not 1 <= page_size <= 100 or not 1 <= ttl_seconds <= 900:
            raise KunlianSyncConflictError()
        async with self._session() as session:
            state = await self._connection(session, connection_id)
            now = self.clock()
            if lease is not None:
                if (lease.connection_id, lease.owner, lease.key_version, lease.page_size) != (
                    connection_id,
                    owner,
                    key_version,
                    page_size,
                ):
                    raise KunlianSyncConflictError()
                state, _ = await self._locked_lease(session, lease)
                state.lease_until = now + timedelta(seconds=ttl_seconds)
                state.update_time = now
                session.add(state)
                return lease
            if state.lease_until is not None and state.lease_until > now:
                return None
            old_batches = (
                await session.exec(
                    select(KunlianSyncBatch)
                    .where(
                        KunlianSyncBatch.connection_id == connection_id,
                        KunlianSyncBatch.status.in_(("FETCHING", "VALIDATING")),
                    )
                    .with_for_update()
                )
            ).all()
            for old in old_batches:
                old.status = "ABANDONED"
                old.completed_at = old.update_time = now
                session.add(old)
            state.sync_fence += 1
            state.lease_owner = owner
            state.lease_until = now + timedelta(seconds=ttl_seconds)
            state.update_time = now
            batch = KunlianSyncBatch(
                connection_id=connection_id,
                fence=state.sync_fence,
                requested_version=state.sync_requested_version,
                key_version=key_version,
                page_size=page_size,
                started_at=now,
            )
            session.add(state)
            session.add(batch)
            await session.flush()
            return DirectoryLease(connection_id, batch.batch_id, owner, state.sync_fence, key_version, page_size)

    async def stage_page(
        self,
        lease: DirectoryLease,
        *,
        tenants: list[dict],
        members: list[dict],
        next_cursor_ciphertext: str | None,
        expected_cursor_ciphertext: str | None = None,
        key_version: str | None = None,
        page_size: int | None = None,
        request_id: str | None = None,
    ) -> None:
        try:
            async with self._session() as session:
                _, batch = await self._locked_lease(session, lease, statuses=("FETCHING",))
                if (
                    (key_version is not None and key_version != lease.key_version)
                    or (page_size is not None and page_size != lease.page_size)
                    or expected_cursor_ciphertext != batch.cursor_ciphertext
                ):
                    raise KunlianSyncConflictError()
                if len(members) > lease.page_size or (request_id is not None and len(request_id) > 128):
                    raise KunlianDirectorySyncError()
                for values in tenants:
                    row = KunlianDirectoryTenant.model_validate({**values, "batch_id": lease.batch_id, "tenant_id": 1})
                    old = await session.get(KunlianDirectoryTenant, (row.batch_id, row.external_tenant_id))
                    if old is not None:
                        if (old.status, old.version, old.summary) != (row.status, row.version, row.summary):
                            raise KunlianDirectorySyncError()
                    else:
                        session.add(row)
                        await session.flush()
                for values in members:
                    row = KunlianDirectoryMember.model_validate({**values, "batch_id": lease.batch_id, "tenant_id": 1})
                    session.add(row)
                batch.cursor_ciphertext = next_cursor_ciphertext
                batch.last_request_id = request_id
                batch.counts = {
                    "pages": batch.counts.get("pages", 0) + 1,
                    "members": batch.counts.get("members", 0) + len(members),
                }
                batch.update_time = self.clock()
                if next_cursor_ciphertext is None:
                    batch.status = "VALIDATING"
                session.add(batch)
                await session.flush()
        except IntegrityError as exc:
            raise KunlianDirectorySyncError() from exc

    async def mark_failed(self, lease: DirectoryLease, reason: str, *, abandoned: bool = False) -> None:
        reasons = {
            "UPSTREAM_UNAVAILABLE",
            "RESUME_CONFLICT",
            "DIRECTORY_INVALID",
            "CURSOR_INVALID",
            "ACCESS_DENIED",
            "CREDENTIAL_INVALID",
            "NETWORK_ACCESS_DENIED",
            "RATE_LIMITED",
            "NETWORK_ERROR",
            "SYNC_TIMEOUT",
            "SYNC_FAILED",
        }
        if reason not in reasons:
            raise KunlianDirectorySyncError()
        async with self._session() as session:
            state, batch = await self._locked_lease(session, lease)
            batch.status = "ABANDONED" if abandoned else "FAILED"
            batch.reason_code = reason
            batch.completed_at = batch.update_time = self.clock()
            state.lease_until = self.clock()
            state.lease_owner = None
            session.add(batch)
            session.add(state)

    @staticmethod
    def _digest(value) -> str:
        return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    async def bind_tenant(
        self,
        connection_id: str,
        external_tenant_id: str,
        *,
        verified_local_tenant_id: int,
        expected_revision: int | None,
        enabled: bool = True,
        actor=None,
    ) -> int:
        # 本地租户的存在和管理资格必须由 tenant Owner 在调用前确认。
        if verified_local_tenant_id <= 0 or not external_tenant_id or len(external_tenant_id) > 64:
            raise KunlianBindingConflictError()
        try:
            async with self._session() as session:
                await self._connection(session, connection_id)
                row = await session.get(KunlianTenantBinding, (connection_id, external_tenant_id))
                if row is None:
                    if expected_revision is not None:
                        raise KunlianBindingConflictError()
                    row = KunlianTenantBinding(
                        connection_id=connection_id,
                        external_tenant_id=external_tenant_id,
                        local_tenant_id=verified_local_tenant_id,
                        enabled=enabled,
                    )
                else:
                    if row.revision != expected_revision:
                        raise KunlianBindingConflictError()
                    if row.materialized and (row.local_tenant_id != verified_local_tenant_id or enabled):
                        raise KunlianBindingConflictError()
                    row.revision += 1
                    row.local_tenant_id = verified_local_tenant_id
                    row.enabled = enabled
                    bindings = (
                        await session.exec(
                            select(KunlianIdentityBinding)
                            .where(
                                KunlianIdentityBinding.connection_id == connection_id,
                                KunlianIdentityBinding.external_tenant_id == external_tenant_id,
                            )
                            .order_by(KunlianIdentityBinding.identity_key)
                            .with_for_update()
                        )
                    ).all()
                    for binding in bindings:
                        binding.auth_epoch += 1
                        binding.admission_status = "MAPPING_CHANGED"
                        binding.projection_status = "PENDING"
                        binding.update_time = self.clock()
                        session.add(binding)
                row.update_time = self.clock()
                session.add(row)
                if actor is not None:
                    self._audit(
                        session,
                        actor=actor,
                        action="kunlian.tenant_binding.update",
                        target_id=connection_id,
                        metadata={
                            "external_tenant_id": external_tenant_id,
                            "local_tenant_id": verified_local_tenant_id,
                            "revision": row.revision,
                            "enabled": enabled,
                        },
                    )
                await session.flush()
                return row.revision
        except IntegrityError as exc:
            raise KunlianBindingConflictError() from exc

    async def record_manual_override(self, identity_key: str, disabled: bool, *, expected_revision: str) -> None:
        async with self._session() as session:
            # 先读取连接标识。实际修改仍在连接→身份的固定锁顺序内完成。
            initial = await session.get(KunlianIdentityBinding, identity_key)
            if initial is None:
                raise KunlianBindingConflictError()
            await self._connection(session, initial.connection_id)
            row = (
                await session.exec(
                    select(KunlianIdentityBinding)
                    .where(KunlianIdentityBinding.identity_key == identity_key)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).first()
            if row is None or row.source_revision != expected_revision:
                raise KunlianBindingConflictError()
            if row.local_override != disabled:
                row.local_override = disabled
                row.auth_epoch += 1
                row.update_time = self.clock()
                session.add(row)

    @asynccontextmanager
    async def manual_override_scope(self, user_id: int, *, disabled: bool):
        if type(user_id) is not int or user_id <= 0 or type(disabled) is not bool:
            raise KunlianBindingConflictError()
        async with self._session() as session:
            initial = (
                await session.exec(
                    select(KunlianIdentityBinding).where(KunlianIdentityBinding.local_user_id == user_id)
                )
            ).first()
            if initial is None:
                raise KunlianBindingConflictError()
            await self._connection(session, initial.connection_id)
            row = (
                await session.exec(
                    select(KunlianIdentityBinding)
                    .where(KunlianIdentityBinding.identity_key == initial.identity_key)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).first()
            if row is None or row.local_user_id != user_id:
                raise KunlianBindingConflictError()
            transaction = session.get_transaction()
            source_revision, original_epoch = row.source_revision, row.auth_epoch

            async def assert_current():
                if session.get_transaction() is not transaction or not transaction.is_active:
                    raise KunlianSyncConflictError()
                with session.no_autoflush:
                    current = (
                        await session.exec(
                            select(KunlianIdentityBinding.source_revision, KunlianIdentityBinding.auth_epoch)
                            .where(KunlianIdentityBinding.identity_key == row.identity_key)
                            .with_for_update()
                        )
                    ).first()
                if current != (source_revision, original_epoch):
                    raise KunlianSyncConflictError()

            if row.local_override != disabled:
                row.local_override = disabled
                row.auth_epoch += 1
                row.update_time = self.clock()
                session.add(row)
            yield row.identity_key, row.admission_status == "ACTIVE", source_revision, assert_current

    async def _validate_staged_batch(self, session, lease):
        tenants = (
            await session.exec(select(KunlianDirectoryTenant).where(KunlianDirectoryTenant.batch_id == lease.batch_id))
        ).all()
        members = (
            await session.exec(select(KunlianDirectoryMember).where(KunlianDirectoryMember.batch_id == lease.batch_id))
        ).all()
        by_tenant = {t.external_tenant_id: t for t in tenants}
        seen_subjects = set()
        for member in members:
            key = (member.external_tenant_id, member.subject)
            if (
                not member.member_id
                or not member.subject
                or not member.status
                or member.external_tenant_id not in by_tenant
                or key in seen_subjects
            ):
                raise KunlianDirectorySyncError()
            seen_subjects.add(key)
        if any(not t.external_tenant_id or not t.status for t in tenants):
            raise KunlianDirectorySyncError()
        return by_tenant, members

    async def validate_staged_batch(self, lease: DirectoryLease) -> None:
        async with self._session() as session:
            await self._locked_lease(session, lease, statuses=("VALIDATING",))
            await self._validate_staged_batch(session, lease)

    async def _reconcile_members(self, session, connection_id, issuer, tenants, members, mappings, *, only_tenant=None):
        bindings = (
            await session.exec(
                select(KunlianIdentityBinding)
                .where(
                    KunlianIdentityBinding.connection_id == connection_id,
                    KunlianIdentityBinding.external_tenant_id == only_tenant if only_tenant else True,
                )
                .order_by(KunlianIdentityBinding.identity_key)
                .with_for_update()
            )
        ).all()
        by_key = {b.identity_key: b for b in bindings}
        by_member = {(b.external_tenant_id, b.member_id): b for b in bindings}
        incoming = {}
        for member in members:
            mapping = mappings.get(member.external_tenant_id)
            if mapping is None:
                continue
            key = self._digest(["kunlian", issuer, member.external_tenant_id, member.subject])
            old = by_key.get(key)
            old_member = by_member.get((member.external_tenant_id, member.member_id))
            if (
                old is not None
                and (old.issuer, old.subject, old.external_tenant_id, old.member_id)
                != (issuer, member.subject, member.external_tenant_id, member.member_id)
            ) or (old_member is not None and old_member.identity_key != key):
                raise KunlianBindingConflictError()
            # 同一自然身份不能跨连接认领已有绑定。
            if old is None and await session.get(KunlianIdentityBinding, key) is not None:
                raise KunlianBindingConflictError()
            tenant = tenants[member.external_tenant_id]
            if not mapping.enabled:
                admission = "MAPPING_DISABLED"
            elif tenant.status != "ACTIVE":
                admission = "TENANT_UNAVAILABLE"
            elif member.deleted:
                admission = "DELETED"
            elif member.status == "ACTIVE":
                admission = "ACTIVE"
            elif member.status in ("INVITED", "DISABLED", "LEFT"):
                admission = member.status
            else:
                admission = "UNKNOWN"
            fingerprint = self._digest(
                {
                    "member": member.model_dump(exclude={"batch_id", "tenant_id", "create_time", "update_time"}),
                    "tenant": tenant.model_dump(exclude={"batch_id", "tenant_id", "create_time", "update_time"}),
                    "mapping": [mapping.local_tenant_id, mapping.revision, mapping.enabled],
                }
            )
            if old is None:
                old = KunlianIdentityBinding(
                    identity_key=key,
                    connection_id=connection_id,
                    issuer=issuer,
                    subject=member.subject,
                    external_tenant_id=member.external_tenant_id,
                    member_id=member.member_id,
                    source_revision=fingerprint,
                    admission_status=admission,
                )
                bindings.append(old)
            incoming[key] = (admission, fingerprint)
        for binding in bindings:
            admission, fingerprint = incoming.get(
                binding.identity_key,
                (
                    "UNKNOWN",
                    self._digest(
                        [
                            "missing",
                            binding.identity_key,
                            mappings.get(binding.external_tenant_id).revision
                            if binding.external_tenant_id in mappings
                            else None,
                        ]
                    ),
                ),
            )
            if binding.admission_status == "ACTIVE" and admission != "ACTIVE":
                binding.auth_epoch += 1
            if binding.source_revision != fingerprint:
                binding.source_revision = fingerprint
                binding.projection_status = "PENDING"
            binding.admission_status = admission
            binding.update_time = self.clock()
            session.add(binding)

    async def publish_directory(self, lease: DirectoryLease, *, issuer: str) -> str:
        if not issuer:
            raise KunlianDirectorySyncError()
        async with self._session() as session:
            state, batch = await self._locked_lease(session, lease, statuses=("VALIDATING",))
            tenants, members = await self._validate_staged_batch(session, lease)
            mappings = {
                row.external_tenant_id: row
                for row in (
                    await session.exec(
                        select(KunlianTenantBinding).where(KunlianTenantBinding.connection_id == lease.connection_id)
                    )
                ).all()
            }
            await self._reconcile_members(session, lease.connection_id, issuer, tenants, members, mappings)
            # 长事务结束前再次核对租约。任何不满足均回滚完整发布。
            if state.lease_until <= self.clock():
                raise KunlianSyncConflictError()
            state.active_batch_id = batch.batch_id
            state.sync_completed_version = max(state.sync_completed_version, batch.requested_version)
            state.lease_owner = None
            state.lease_until = self.clock()
            state.update_time = self.clock()
            batch.status = "PUBLISHED"
            batch.completed_at = batch.update_time = self.clock()
            session.add(state)
            session.add(batch)
            await session.flush()
            return batch.batch_id

    async def has_local_user_binding(self, user_id: int) -> bool:
        async with self._session() as session:
            key = (
                await session.exec(
                    select(KunlianIdentityBinding.identity_key)
                    .where(KunlianIdentityBinding.local_user_id == user_id)
                    .limit(1)
                )
            ).first()
            return key is not None

    async def get_binding(self, identity_key: str) -> KunlianIdentityBinding | None:
        async with self._session() as session:
            return await session.get(KunlianIdentityBinding, identity_key)

    async def get_tenant_binding(self, connection_id: str, external_tenant_id: str) -> KunlianTenantBinding | None:
        async with self._session() as session:
            return await session.get(KunlianTenantBinding, (connection_id, external_tenant_id))

    async def resolve_user_mapping(self, user_id: int):
        from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping

        async with self._session() as session:
            binding = (
                await session.exec(
                    select(KunlianIdentityBinding).where(KunlianIdentityBinding.local_user_id == user_id)
                )
            ).first()
            if binding is None:
                raise KunlianDirectoryNotReadyError()
            state = await session.get(KunlianConnectionState, binding.connection_id)
            mapping = await session.get(KunlianTenantBinding, (binding.connection_id, binding.external_tenant_id))
            if (
                state is None
                or not state.enabled
                or mapping is None
                or not mapping.enabled
                or binding.admission_status != "ACTIVE"
                or binding.local_override
            ):
                raise KunlianIdentityUnavailableError()
            if (
                not mapping.materialized
                or binding.projection_status != "SUCCEEDED"
                or binding.projected_revision != binding.source_revision
            ):
                raise KunlianDirectoryNotReadyError()
            return KunlianTenantMapping(
                connection_id=mapping.connection_id,
                external_tenant_id=mapping.external_tenant_id,
                local_tenant_id=mapping.local_tenant_id,
                revision=mapping.revision,
            )

    @classmethod
    def identity_key(cls, issuer: str, external_tenant_id: str, subject: str) -> str:
        return cls._digest(["kunlian", issuer, external_tenant_id, subject])

    async def get_lease(self, batch_id: str, fence: int) -> DirectoryLease:
        async with self._session() as session:
            batch = await session.get(KunlianSyncBatch, batch_id)
            if batch is None or batch.fence != fence:
                raise KunlianSyncConflictError()
            state = await self._connection(session, batch.connection_id)
            lease = DirectoryLease(
                batch.connection_id, batch_id, state.lease_owner, fence, batch.key_version, batch.page_size
            )
            await self._locked_lease(session, lease)
            return lease

    async def get_status(self, connection_id: str) -> dict:
        async with self._session() as session:
            state = await session.get(KunlianConnectionState, connection_id)
            if state is None:
                raise KunlianDirectoryNotReadyError()
            latest = (
                await session.exec(
                    select(KunlianSyncBatch)
                    .where(KunlianSyncBatch.connection_id == connection_id)
                    .order_by(KunlianSyncBatch.fence.desc())
                    .limit(1)
                )
            ).first()
            active = await session.get(KunlianSyncBatch, state.active_batch_id) if state.active_batch_id else None
            # 只取状态和修订。诊断查询不加载完整外部成员摘要。
            bindings = (
                await session.exec(
                    select(
                        KunlianIdentityBinding.projection_status,
                        KunlianIdentityBinding.source_revision,
                        KunlianIdentityBinding.projected_revision,
                    ).where(KunlianIdentityBinding.connection_id == connection_id)
                )
            ).all()
            mapped = (
                await session.exec(
                    select(KunlianTenantBinding.external_tenant_id).where(
                        KunlianTenantBinding.connection_id == connection_id
                    )
                )
            ).all()
            unmapped = (
                (
                    await session.exec(
                        select(KunlianDirectoryMember.member_id).where(
                            KunlianDirectoryMember.batch_id == state.active_batch_id,
                            KunlianDirectoryMember.external_tenant_id.not_in(mapped),
                        )
                    )
                ).all()
                if active
                else []
            )
            failed = sum(row[0] == "FAILED" for row in bindings)
            pending = sum(row[0] != "FAILED" and (row[0] != "SUCCEEDED" or row[1] != row[2]) for row in bindings)
            projection = "FAILED" if failed else "PENDING" if pending else "UNMAPPED" if unmapped else "SUCCEEDED"
            directory = (
                "FETCHING"
                if latest and latest.status in ("FETCHING", "VALIDATING")
                else "FAILED"
                if latest and latest.status in ("FAILED", "ABANDONED")
                else "PUBLISHED"
                if active
                else "UNINITIALIZED"
            )
            return {
                "connection_id": connection_id,
                "directory_status": directory,
                "projection_status": projection,
                "active_batch_id": state.active_batch_id,
                "running_batch_id": latest.batch_id if latest and directory == "FETCHING" else None,
                "member_count": active.counts.get("members", 0) if active else 0,
                "unmapped_count": len(unmapped),
                "projection_pending": pending,
                "projection_failed": failed,
                "last_published_at": active.completed_at if active else None,
                "last_reason_code": latest.reason_code if latest else None,
                "last_request_id": latest.last_request_id if latest else None,
                "sync_requested_version": state.sync_requested_version,
                "sync_completed_version": state.sync_completed_version,
                "enabled": state.enabled,
                "policy_revision": state.policy_revision,
                "last_run_at": latest.started_at if latest else None,
            }

    def _seal(self, value: str) -> str:
        if not self.key_version or not callable(self.encrypt_value):
            raise KunlianDependencyUnavailableError()
        try:
            sealed = self.encrypt_value(value)
            if isinstance(sealed, bytes):
                sealed = sealed.decode("ascii")
            if not isinstance(sealed, str) or not sealed or sealed == value:
                raise ValueError("Invalid encryption result")
            return sealed
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise KunlianDependencyUnavailableError() from None

    def _open(self, value: str, key_version: str) -> SecretStr:
        if key_version != self.key_version or not callable(self.decrypt_value):
            raise KunlianDependencyUnavailableError()
        try:
            opened = self.decrypt_value(value)
            if not isinstance(opened, str) or not opened:
                raise ValueError("Invalid decryption result")
            return SecretStr(opened)
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise KunlianDependencyUnavailableError() from None

    @staticmethod
    def _hash_equals(left, right) -> bool:
        return all(
            isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
            for value in (left, right)
        ) and compare_digest(left, right)

    @staticmethod
    def _reference_hash(reference: SecretStr | str) -> str:
        raw = reference.get_secret_value() if isinstance(reference, SecretStr) else reference
        if not isinstance(raw, str) or not raw or len(raw) > 512:
            raise KunlianSessionExpiredError()
        return sha256(raw.encode()).hexdigest()

    async def _binding_lock(self, session, binding_id):
        row = (
            await session.exec(
                select(KunlianIdentityBinding)
                .where(KunlianIdentityBinding.identity_key == binding_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        if row is None:
            raise KunlianSessionExpiredError()
        return row

    async def _session_lock(self, session, session_hash):
        row = (
            await session.exec(
                select(KunlianWebSession)
                .where(KunlianWebSession.session_hash == session_hash)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        if row is None:
            raise KunlianSessionExpiredError()
        return row

    async def _session_owner(self, session, session_hash, *, lock_connection=False):
        initial = await session.get(KunlianWebSession, session_hash)
        if initial is None:
            raise KunlianSessionExpiredError()
        binding = await session.get(KunlianIdentityBinding, initial.binding_id)
        if binding is None:
            raise KunlianSessionExpiredError()
        connection = (
            await self._connection(session, binding.connection_id)
            if lock_connection
            else await session.get(KunlianConnectionState, binding.connection_id)
        )
        binding = await self._binding_lock(session, initial.binding_id)
        web = await self._session_lock(session, session_hash)
        return connection, binding, web

    async def issue_or_replay_handoff(
        self,
        connection_id,
        handoff_id,
        request_digest,
        *,
        binding_id,
        expected_source_revision,
        expected_auth_epoch,
        browser_binding_hash,
        client_id,
        sid,
        workspace_id,
        access_token: SecretStr,
        id_token: SecretStr,
        access_token_expires_at,
        hard_expires_at,
        signing_context: dict,
        allow_multi_login: bool = True,
        expected_policy_revision: int | None = None,
    ) -> IssuedKunlianSession:
        now = self.clock()
        if (
            not handoff_id
            or len(handoff_id) > 64
            or len(request_digest) != 64
            or hard_expires_at <= now
            or hard_expires_at > now + timedelta(hours=8)
            or access_token_expires_at <= now
            or set(signing_context) - {"user_id", "tenant_id", "token_version", "user_name"}
        ):
            raise KunlianSyncConflictError()
        async with self._session() as session:
            connection = await self._connection(session, connection_id)
            binding = await self._binding_lock(session, binding_id)
            mapping = await session.get(KunlianTenantBinding, (connection_id, binding.external_tenant_id))
            if not connection.enabled or (
                expected_policy_revision is not None and connection.policy_revision != expected_policy_revision
            ):
                raise KunlianDependencyUnavailableError()
            if (
                binding.connection_id != connection_id
                or binding.source_revision != expected_source_revision
                or binding.auth_epoch != expected_auth_epoch
                or binding.admission_status != "ACTIVE"
                or binding.local_override
                or binding.local_user_id is None
                or binding.projected_revision != binding.source_revision
                or binding.projection_status != "SUCCEEDED"
                or mapping is None
                or not mapping.enabled
                or signing_context.get("user_id") != binding.local_user_id
                or signing_context.get("tenant_id") != mapping.local_tenant_id
            ):
                raise KunlianSessionExpiredError()
            receipt = await session.get(KunlianHandoffReceipt, handoff_id)
            if receipt is not None:
                if receipt.connection_id != connection_id or not self._hash_equals(
                    receipt.request_digest, request_digest
                ):
                    raise KunlianSyncConflictError()
                web = await self._session_lock(session, receipt.session_hash)
                if (
                    web.binding_id != binding_id
                    or web.state != "ACTIVE"
                    or web.hard_expires_at <= now
                    or web.access_token_expires_at <= now
                    or receipt.expires_at <= now
                    or web.auth_epoch_at_issue != binding.auth_epoch
                    or not self._hash_equals(web.browser_binding_hash, browser_binding_hash)
                    or receipt.signing_context.get("token_version") != signing_context.get("token_version")
                ):
                    raise KunlianSessionExpiredError()
                return IssuedKunlianSession(
                    self._open(receipt.session_ref_ciphertext, web.token_key_version),
                    web.session_hash,
                    web.hard_expires_at,
                    dict(receipt.signing_context),
                )
            if not allow_multi_login:
                previous = (
                    await session.exec(
                        select(KunlianWebSession)
                        .where(
                            KunlianWebSession.binding_id == binding_id,
                            KunlianWebSession.state.in_(("ACTIVE", "REAUTH_REQUIRED")),
                        )
                        .order_by(KunlianWebSession.session_hash)
                        .with_for_update()
                    )
                ).all()
                for old in previous:
                    old.state, old.revoked_at, old.update_time = "REVOKED", now, now
                    old.csrf_epoch += 1
                    session.add(old)
            reference = token_urlsafe(32)
            session_hash = self._reference_hash(reference)
            context = dict(
                signing_context,
                iat=int(now.replace(tzinfo=UTC).timestamp()),
                exp=int(hard_expires_at.replace(tzinfo=UTC).timestamp()),
            )
            web = KunlianWebSession.model_validate(
                {
                    "session_hash": session_hash,
                    "binding_id": binding_id,
                    "auth_epoch_at_issue": binding.auth_epoch,
                    "browser_binding_hash": browser_binding_hash,
                    "client_id": client_id,
                    "sid": sid,
                    "workspace_id": workspace_id,
                    "access_token_ciphertext": self._seal(access_token.get_secret_value()),
                    "id_token_ciphertext": self._seal(id_token.get_secret_value()),
                    "token_key_version": self.key_version,
                    "access_token_expires_at": access_token_expires_at,
                    "hard_expires_at": hard_expires_at,
                    "issued_at": now,
                }
            )
            session.add(web)
            await session.flush()
            receipt = KunlianHandoffReceipt(
                handoff_id=handoff_id,
                connection_id=connection_id,
                request_digest=request_digest,
                session_hash=session_hash,
                session_ref_ciphertext=self._seal(reference),
                signing_context=context,
                expires_at=min(hard_expires_at, now + timedelta(seconds=60)),
            )
            session.add(receipt)
            await session.flush()
            return IssuedKunlianSession(SecretStr(reference), session_hash, hard_expires_at, context)

    async def load_admission_facts(self, reference: SecretStr | str, *, protocol_only=False) -> KunlianAdmissionFacts:
        error = None
        result = None
        async with self._session() as session:
            connection, binding, web = await self._session_owner(session, self._reference_hash(reference))
            now = self.clock()
            if web.hard_expires_at <= now or web.state == "EXPIRED":
                web.state = "EXPIRED"
                web.access_token_ciphertext = web.id_token_ciphertext = ""
                web.update_time = now
                session.add(web)
                error = KunlianSessionExpiredError()
            elif protocol_only:
                receipt = await self._receipt_for_session(session, web.session_hash)
                result = KunlianAdmissionFacts(web, binding, signing_context=dict(receipt.signing_context))
            elif web.state in ("REVOKED", "EXPIRED") or web.auth_epoch_at_issue != binding.auth_epoch:
                if web.state != "EXPIRED":
                    web.state, web.revoked_at, web.update_time = "REVOKED", now, now
                    session.add(web)
                error = KunlianSessionExpiredError()
            elif connection is None or not connection.enabled:
                error = KunlianDependencyUnavailableError()
            elif web.state != "ACTIVE" or web.access_token_expires_at <= now:
                web.state, web.update_time = "REAUTH_REQUIRED", now
                session.add(web)
                error = KunlianSessionExpiredError()
            else:
                mapping = await session.get(KunlianTenantBinding, (binding.connection_id, binding.external_tenant_id))
                if (
                    binding.admission_status != "ACTIVE"
                    or binding.local_override
                    or binding.local_user_id is None
                    or mapping is None
                    or not mapping.enabled
                ):
                    web.state, web.revoked_at, web.update_time = "REVOKED", now, now
                    session.add(web)
                    error = KunlianSessionExpiredError()
                elif binding.projected_revision != binding.source_revision or binding.projection_status != "SUCCEEDED":
                    error = KunlianDirectoryNotReadyError()
                else:
                    receipt = await self._receipt_for_session(session, web.session_hash)
                    batch = (
                        await session.get(KunlianSyncBatch, connection.active_batch_id)
                        if connection.active_batch_id
                        else None
                    )
                    result = KunlianAdmissionFacts(
                        web,
                        binding,
                        access_token=self._open(web.access_token_ciphertext, web.token_key_version),
                        mapping=mapping,
                        published_batch=batch,
                        signing_context=dict(receipt.signing_context),
                        connection=connection,
                    )
        # 状态失效必须先提交。不能在事务中抛错再将撤销回滚。
        if error is not None:
            raise error
        return result

    async def revoke_session(self, reference: SecretStr | str, reason: str) -> None:
        if reason not in {"LOGOUT", "INTROSPECTION_INACTIVE", "IDENTITY_CHANGED", "DISABLED"}:
            raise KunlianTrustRejectedError()
        async with self._session() as session:
            _, _, web = await self._session_owner(session, self._reference_hash(reference), lock_connection=True)
            if web.state not in ("REVOKED", "EXPIRED"):
                web.state = "REVOKED"
                web.revoked_at = web.update_time = self.clock()
                web.csrf_epoch += 1
                session.add(web)

    async def mark_reauthentication_required(self, reference: SecretStr | str):
        async with self._session() as session:
            _, _, web = await self._session_owner(session, self._reference_hash(reference), lock_connection=True)
            if web.state == "ACTIVE":
                web.state = "REAUTH_REQUIRED"
                web.update_time = self.clock()
                session.add(web)

    async def _receipt_for_session(self, session, session_hash):
        rows = (
            await session.exec(
                select(KunlianHandoffReceipt)
                .where(KunlianHandoffReceipt.session_hash == session_hash)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(rows) != 1:
            raise KunlianTrustRejectedError()
        return rows[0]

    async def issue_logout_ticket(self, reference: SecretStr | str, browser_binding_hash: str) -> SecretStr | None:
        async with self._session() as session:
            _, _, web = await self._session_owner(session, self._reference_hash(reference), lock_connection=True)
            if (
                web.state != "REVOKED"
                or web.hard_expires_at <= self.clock()
                or not self._hash_equals(web.browser_binding_hash, browser_binding_hash)
            ):
                raise KunlianTrustRejectedError()
            receipt = await self._receipt_for_session(session, web.session_hash)
            if receipt.logout_ticket_consumed_at is not None:
                # 已交接的退出不能再读取 Hint。仍可确认这个本地会话已撤销。
                return None
            ticket = token_urlsafe(32)
            receipt.logout_ticket_hash = self._reference_hash(ticket)
            receipt.logout_ticket_expires_at = min(web.hard_expires_at, self.clock() + timedelta(seconds=60))
            receipt.update_time = self.clock()
            session.add(receipt)
            return SecretStr(ticket)

    async def redeem_logout_ticket(
        self,
        ticket: SecretStr | str,
        browser_binding_hash: str,
        *,
        expected_connection_id: str | None = None,
        expected_client_id: str | None = None,
    ) -> KunlianLogoutMaterial:
        ticket_hash = self._reference_hash(ticket)
        async with self._session() as session:
            initial = (
                await session.exec(
                    select(KunlianHandoffReceipt).where(KunlianHandoffReceipt.logout_ticket_hash == ticket_hash)
                )
            ).first()
            if initial is None:
                raise KunlianTrustRejectedError()
            _, binding, web = await self._session_owner(session, initial.session_hash, lock_connection=True)
            receipt = await self._receipt_for_session(session, web.session_hash)
            if (
                receipt.logout_ticket_hash != ticket_hash
                or receipt.logout_ticket_consumed_at is not None
                or receipt.logout_ticket_expires_at is None
                or receipt.logout_ticket_expires_at <= self.clock()
                or web.hard_expires_at <= self.clock()
                or web.state != "REVOKED"
                or (expected_connection_id is not None and binding.connection_id != expected_connection_id)
                or (expected_client_id is not None and web.client_id != expected_client_id)
                or not self._hash_equals(web.browser_binding_hash, browser_binding_hash)
            ):
                raise KunlianTrustRejectedError()
            material = KunlianLogoutMaterial(self._open(web.id_token_ciphertext, web.token_key_version), web.client_id)
            receipt.logout_ticket_consumed_at = receipt.update_time = self.clock()
            session.add(receipt)
            return material

    async def expire_sessions(self, connection_id: str, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise KunlianSyncConflictError()
        async with self._session() as session:
            await self._connection(session, connection_id)
            rows = (
                await session.exec(
                    select(KunlianWebSession)
                    .join(KunlianIdentityBinding, KunlianWebSession.binding_id == KunlianIdentityBinding.identity_key)
                    .where(
                        KunlianIdentityBinding.connection_id == connection_id,
                        KunlianWebSession.hard_expires_at <= self.clock(),
                        KunlianWebSession.state != "EXPIRED",
                    )
                    .order_by(KunlianWebSession.session_hash)
                    .limit(limit)
                    .with_for_update()
                )
            ).all()
            for row in rows:
                row.state = "EXPIRED"
                row.access_token_ciphertext = row.id_token_ciphertext = ""
                row.update_time = self.clock()
                session.add(row)
            return len(rows)

    async def expire_handoff_material(self, connection_id: str, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise KunlianSyncConflictError()
        async with self._session() as session:
            await self._connection(session, connection_id)
            rows = (
                await session.exec(
                    select(KunlianHandoffReceipt)
                    .where(
                        KunlianHandoffReceipt.connection_id == connection_id,
                        KunlianHandoffReceipt.expires_at <= self.clock(),
                        func.length(KunlianHandoffReceipt.session_ref_ciphertext) > 0,
                    )
                    .order_by(KunlianHandoffReceipt.handoff_id)
                    .limit(limit)
                    .with_for_update()
                )
            ).all()
            changed = 0
            for row in rows:
                if row.session_ref_ciphertext:
                    row.session_ref_ciphertext = ""
                    row.update_time = self.clock()
                    session.add(row)
                    changed += 1
            return changed

    async def _projection_binding(self, session, identity_key):
        if (
            not isinstance(identity_key, str)
            or len(identity_key) != 64
            or any(c not in "0123456789abcdef" for c in identity_key)
        ):
            raise KunlianBindingConflictError()
        initial = await session.get(KunlianIdentityBinding, identity_key)
        if initial is None:
            raise KunlianDirectoryNotReadyError()
        await self._connection(session, initial.connection_id)
        row = (
            await session.exec(
                select(KunlianIdentityBinding)
                .where(KunlianIdentityBinding.identity_key == identity_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        if row is None or self.identity_key(row.issuer, row.external_tenant_id, row.subject) != identity_key:
            raise KunlianBindingConflictError()
        return row

    async def freeze_projection_mapping(self, identity_key: str, *, onboarding_policy=None) -> None:
        # 此事务必须先于任何账号物化提交。后续失败也不解除冻结。
        async with self._session() as session:
            row = await self._projection_binding(session, identity_key)
            if onboarding_policy is not None:
                await self._check_onboarding_identity(session, row, onboarding_policy)
            mapping = await session.get(KunlianTenantBinding, (row.connection_id, row.external_tenant_id))
            if mapping is None or mapping.local_tenant_id <= 0:
                raise KunlianDirectoryNotReadyError()
            if not mapping.materialized:
                if not mapping.enabled:
                    raise KunlianIdentityUnavailableError()
                mapping.materialized = True
                mapping.update_time = self.clock()
                session.add(mapping)

    @asynccontextmanager
    async def projection_scope(self, identity_key: str, *, onboarding_policy=None):
        from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping

        async with self._session() as session:
            row = await self._projection_binding(session, identity_key)
            if onboarding_policy is not None:
                await self._check_onboarding_identity(session, row, onboarding_policy)
            mapping = await session.get(KunlianTenantBinding, (row.connection_id, row.external_tenant_id))
            if mapping is None or not mapping.materialized:
                raise KunlianDirectoryNotReadyError()
            member = (
                await session.exec(
                    select(KunlianDirectoryMember)
                    .join(KunlianSyncBatch, KunlianSyncBatch.batch_id == KunlianDirectoryMember.batch_id)
                    .where(
                        KunlianSyncBatch.connection_id == row.connection_id,
                        KunlianSyncBatch.status == "PUBLISHED",
                        KunlianDirectoryMember.external_tenant_id == row.external_tenant_id,
                        KunlianDirectoryMember.member_id == row.member_id,
                        KunlianDirectoryMember.subject == row.subject,
                    )
                    .order_by(KunlianSyncBatch.fence.desc())
                    .limit(1)
                )
            ).first()
            if member is None:
                raise KunlianDirectoryNotReadyError()
            facts = KunlianProjectionFacts(
                row.identity_key,
                row.connection_id,
                row.issuer,
                row.subject,
                row.external_tenant_id,
                row.member_id,
                row.source_revision,
                row.auth_epoch,
                row.admission_status == "ACTIVE" and not row.local_override and mapping.enabled,
                row.local_user_id,
                row.projection_status == "SUCCEEDED"
                and row.projected_revision == row.source_revision
                and row.local_user_id is not None,
                KunlianTenantMapping(
                    connection_id=mapping.connection_id,
                    external_tenant_id=mapping.external_tenant_id,
                    local_tenant_id=mapping.local_tenant_id,
                    revision=mapping.revision,
                ),
                dict(member.summary),
            )
            original_transaction = session.get_transaction()
            current_context = (row.source_revision, row.auth_epoch, row.local_override, row.admission_status)

            async def assert_current():
                if session.get_transaction() is not original_transaction or not original_transaction.is_active:
                    raise KunlianSyncConflictError()
                with session.no_autoflush:
                    current = (
                        await session.exec(
                            select(
                                KunlianIdentityBinding.source_revision,
                                KunlianIdentityBinding.auth_epoch,
                                KunlianIdentityBinding.local_override,
                                KunlianIdentityBinding.admission_status,
                            )
                            .where(KunlianIdentityBinding.identity_key == identity_key)
                            .with_for_update()
                        )
                    ).first()
                if current != current_context:
                    raise KunlianSyncConflictError()

            async def complete(user_id: int):
                await assert_current()
                if type(user_id) is not int or user_id <= 0 or row.local_user_id not in (None, user_id):
                    raise KunlianBindingConflictError()
                row.local_user_id = user_id
                row.projected_revision = facts.source_revision
                row.projection_status = "SUCCEEDED"
                row.update_time = self.clock()
                session.add(row)
                await session.flush()

            yield facts, assert_current, complete

    async def mark_projection_failed(self, identity_key: str, *, source_revision: str, auth_epoch: int) -> bool:
        async with self._session() as session:
            row = await self._projection_binding(session, identity_key)
            if (
                row.source_revision != source_revision
                or row.auth_epoch != auth_epoch
                or (row.projection_status == "SUCCEEDED" and row.projected_revision == row.source_revision)
            ):
                return False
            row.projection_status = "FAILED"
            row.update_time = self.clock()
            session.add(row)
            return True

    async def list_projection_candidates(
        self, connection_id: str, *, after_key: str = "", limit: int = 100
    ) -> list[str]:
        from sqlalchemy import or_

        if not 1 <= limit <= 500:
            raise KunlianSyncConflictError()
        async with self._session() as session:
            return list(
                (
                    await session.exec(
                        select(KunlianIdentityBinding.identity_key)
                        .where(
                            KunlianIdentityBinding.connection_id == connection_id,
                            KunlianIdentityBinding.identity_key > after_key,
                            or_(
                                KunlianIdentityBinding.projection_status != "SUCCEEDED",
                                KunlianIdentityBinding.projected_revision.is_(None),
                                KunlianIdentityBinding.projected_revision != KunlianIdentityBinding.source_revision,
                            ),
                        )
                        .order_by(KunlianIdentityBinding.identity_key)
                        .limit(limit)
                    )
                ).all()
            )

    async def _onboarding_batch(self, session, connection_id, policy_revision, max_age_seconds):
        state = await self._connection(session, connection_id)
        batch = await session.get(KunlianSyncBatch, state.active_batch_id) if state.active_batch_id else None
        if (
            not state.enabled
            or state.policy_revision != policy_revision
            or batch is None
            or batch.connection_id != connection_id
            or batch.status != "PUBLISHED"
            or batch.completed_at is None
            or batch.completed_at > self.clock()
            or max_age_seconds is None
            or max_age_seconds <= 0
            or (self.clock() - batch.completed_at).total_seconds() > max_age_seconds
        ):
            raise KunlianDirectoryNotReadyError()
        return batch

    async def _check_onboarding_identity(self, session, binding, policy):
        if binding.connection_id != policy.connection_id or binding.issuer != policy.issuer:
            raise KunlianBindingConflictError()
        await self._onboarding_batch(
            session, policy.connection_id, policy.policy_revision, policy.max_directory_age_seconds
        )

    def _onboarding_tenant(self, tenant, mapping, *, connection_id, issuer, policy_revision, max_age_seconds):
        return KunlianOnboardingTenant(
            connection_id,
            issuer,
            tenant.external_tenant_id,
            tenant.summary.get("name") or tenant.external_tenant_id,
            tenant.batch_id,
            self._digest(tenant.model_dump(exclude={"create_time", "update_time"})),
            policy_revision,
            max_age_seconds,
            mapping.local_tenant_id if mapping else None,
            mapping.revision if mapping else None,
        )

    async def list_onboarding_tenants(
        self, connection_id, *, issuer, policy_revision, max_age_seconds, after_key="", limit=25
    ):
        if not 1 <= limit <= 100 or not isinstance(after_key, str) or len(after_key) > 64:
            raise KunlianSyncConflictError()
        async with self._session() as session:
            batch = await self._onboarding_batch(session, connection_id, policy_revision, max_age_seconds)
            tenants = (
                await session.exec(
                    select(KunlianDirectoryTenant)
                    .where(
                        KunlianDirectoryTenant.batch_id == batch.batch_id,
                        KunlianDirectoryTenant.status == "ACTIVE",
                        KunlianDirectoryTenant.external_tenant_id > after_key,
                    )
                    .order_by(KunlianDirectoryTenant.external_tenant_id)
                    .limit(limit)
                )
            ).all()
            # 禁用映射作为独立失败处理; 不能因此跳过其后的其他租户。
            return [
                self._onboarding_tenant(
                    t,
                    await session.get(KunlianTenantBinding, (connection_id, t.external_tenant_id)),
                    connection_id=connection_id,
                    issuer=issuer,
                    policy_revision=policy_revision,
                    max_age_seconds=max_age_seconds,
                )
                for t in tenants
            ]

    async def assert_onboarding_tenant(self, facts):
        async with self._session() as session:
            await self._current_onboarding_tenant(session, facts)

    async def _current_onboarding_tenant(self, session, facts):
        batch = await self._onboarding_batch(session, facts.connection_id, facts.policy_revision, facts.max_age_seconds)
        tenant = await session.get(KunlianDirectoryTenant, (batch.batch_id, facts.external_tenant_id))
        if (
            batch.batch_id != facts.batch_id
            or tenant is None
            or tenant.status != "ACTIVE"
            or self._digest(tenant.model_dump(exclude={"create_time", "update_time"})) != facts.source_revision
        ):
            raise KunlianSyncConflictError()
        mapping = await session.get(KunlianTenantBinding, (facts.connection_id, facts.external_tenant_id))
        if (mapping.revision if mapping else None) != facts.mapping_revision:
            raise KunlianSyncConflictError()
        if mapping is not None and (
            not mapping.enabled
            or (facts.manual_tenant_id is not None and facts.manual_tenant_id != mapping.local_tenant_id)
        ):
            raise KunlianIdentityUnavailableError()
        return tenant, mapping

    async def bind_onboarded_tenant(self, facts, receipt):
        if receipt.state != "READY" or receipt.source_key != facts.source_key or receipt.local_tenant_id <= 1:
            raise KunlianBindingConflictError()
        try:
            async with self._session() as session:
                tenant, mapping = await self._current_onboarding_tenant(session, facts)
                if mapping is None:
                    mapping = KunlianTenantBinding(
                        connection_id=facts.connection_id,
                        external_tenant_id=facts.external_tenant_id,
                        local_tenant_id=receipt.local_tenant_id,
                    )
                    session.add(mapping)
                    await session.flush()
                elif mapping.local_tenant_id != receipt.local_tenant_id:
                    raise KunlianBindingConflictError()
                members = (
                    await session.exec(
                        select(KunlianDirectoryMember).where(
                            KunlianDirectoryMember.batch_id == facts.batch_id,
                            KunlianDirectoryMember.external_tenant_id == facts.external_tenant_id,
                        )
                    )
                ).all()
                await self._reconcile_members(
                    session,
                    facts.connection_id,
                    facts.issuer,
                    {facts.external_tenant_id: tenant},
                    members,
                    {facts.external_tenant_id: mapping},
                    only_tenant=facts.external_tenant_id,
                )
        except IntegrityError:
            raise KunlianBindingConflictError() from None

    async def list_onboarding_members(self, connection_id, *, policy_revision, max_age_seconds, after_key="", limit=25):
        if not 1 <= limit <= 100 or not isinstance(after_key, str) or len(after_key) > 64:
            raise KunlianSyncConflictError()
        async with self._session() as session:
            await self._onboarding_batch(session, connection_id, policy_revision, max_age_seconds)
            return list(
                (
                    await session.exec(
                        select(KunlianIdentityBinding.identity_key)
                        .where(
                            KunlianIdentityBinding.connection_id == connection_id,
                            KunlianIdentityBinding.identity_key > after_key,
                            KunlianIdentityBinding.admission_status == "ACTIVE",
                            KunlianIdentityBinding.local_override.is_(False),
                            KunlianIdentityBinding.projection_status == "SUCCEEDED",
                            KunlianIdentityBinding.projected_revision == KunlianIdentityBinding.source_revision,
                            KunlianIdentityBinding.local_user_id.is_not(None),
                        )
                        .order_by(KunlianIdentityBinding.identity_key)
                        .limit(limit)
                    )
                ).all()
            )

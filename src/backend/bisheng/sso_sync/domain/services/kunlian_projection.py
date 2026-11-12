"""独立 Owner 投影恢复。旧事务、旧操作和旧回执均不能完成当前投影。"""

import asyncio

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.user.application.external_identity import ExternalShadowIdentity


class KunlianProjectionService:
    def __init__(self, repository, *, user_owner, tenant_owner, timeout_seconds=10):
        self.repository = repository
        self.user_owner = user_owner
        self.tenant_owner = tenant_owner
        self.timeout_seconds = timeout_seconds

    async def _record_failed(self, facts):
        if facts is None:
            return
        try:
            await self.repository.mark_projection_failed(
                facts.identity_key, source_revision=facts.source_revision, auth_epoch=facts.auth_epoch
            )
        except (SQLAlchemyError, KunlianError):
            # 主路径仍然失败。诊断修复不能覆盖新发布或冒充投影成功。
            logger.warning("Kunlian projection failure record unavailable identity={}", facts.identity_key)

    async def ensure_current_membership(self, facts):
        if facts.active:
            with tenant_execution_scope(facts.mapping.local_tenant_id):
                await self.tenant_owner.ensure_external_membership(facts.local_user_id, facts.mapping)

    async def project_identity(self, identity_key: str, *, onboarding_policy=None) -> int:
        facts = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                policy_args = {"onboarding_policy": onboarding_policy} if onboarding_policy is not None else {}
                await self.repository.freeze_projection_mapping(identity_key, **policy_args)
                async with self.repository.projection_scope(identity_key, **policy_args) as (
                    facts,
                    assert_current,
                    complete,
                ):
                    if facts.already_projected:
                        await assert_current()
                        await self.ensure_current_membership(facts)
                        await assert_current()
                        return facts.local_user_id
                    display_name = facts.member_summary.get("display_name")
                    if display_name is None or display_name == "":
                        display_name = facts.subject
                    identity = ExternalShadowIdentity(
                        issuer=facts.issuer,
                        subject=facts.subject,
                        external_tenant_id=facts.external_tenant_id,
                        member_id=facts.member_id,
                        display_name=display_name,
                        active=facts.active,
                    )
                    operation = await self.user_owner.reserve_external_shadow(identity, facts.source_revision)
                    # 预留不能授权写用户。只能在原持锁事务仍有效时派发该操作。
                    await assert_current()
                    uid = await self.user_owner.ensure_external_shadow(
                        identity, facts.source_revision, operation=operation
                    )
                    await assert_current()
                    with tenant_execution_scope(facts.mapping.local_tenant_id):
                        await self.tenant_owner.ensure_external_membership(uid, facts.mapping)
                    receipt = await self.user_owner.read_projection_receipt(operation)
                    if (
                        receipt.user_id != uid
                        or receipt.operation_id != operation.operation_id
                        or receipt.fence != operation.fence
                        or receipt.source_revision != facts.source_revision
                    ):
                        raise KunlianBindingConflictError()
                    await complete(uid)
                    return uid
        except KunlianError:
            await self._record_failed(facts)
            raise
        except (TimeoutError, SQLAlchemyError):
            await self._record_failed(facts)
            raise KunlianDependencyUnavailableError() from None

    async def project_pending(self, connection_id: str, *, after_key="", limit=100) -> dict:
        keys = await self.repository.list_projection_candidates(connection_id, after_key=after_key, limit=limit)
        succeeded = failed = 0
        for key in keys:
            try:
                await self.project_identity(key)
                succeeded += 1
            except KunlianError as exc:
                logger.warning("Kunlian projection failed identity={} reason={}", key, exc.reason_code)
                failed += 1
        return {
            "succeeded": succeeded,
            "failed": failed,
            "next_after_key": keys[-1] if keys else after_key,
            "has_more": len(keys) == limit,
        }

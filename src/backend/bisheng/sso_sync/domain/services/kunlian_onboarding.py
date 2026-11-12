"""从当前完整目录协调原领域, 各阶段独立游标且不缓存允许结果。"""

import asyncio
import json
from hashlib import sha256

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianError,
    KunlianIdentityUnavailableError,
    KunlianTrustRejectedError,
)
from bisheng.tenant.application.external_provision import ExternalTenantCommand
from bisheng.user.application.external_basic_access import BasicAccessCommand


class KunlianOnboardingService:
    # TODO [F130][EXT-01]: 正式租户/Workspace 组合与客户端范围须以昆联确认后的受控配置启用。
    STAGES = ("tenants", "projection", "basic_access")

    def __init__(self, repository, config, *, tenants, users, roles, access, projection, multi_tenant_enabled=True):
        self.repository = repository
        self.config = config
        self.tenants = tenants
        self.users = users
        self.roles = roles
        self.access = access
        self.projection = projection
        self.multi_tenant_enabled = multi_tenant_enabled

    @staticmethod
    def source_key(issuer, external_tenant_id):
        return sha256(
            json.dumps(
                ["kunlian", issuer, external_tenant_id], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    async def _tenant_ready(self, binding):
        if (
            binding is None
            or binding.connection_id != self.config.connection_id
            or binding.issuer != self.config.issuer
        ):
            raise KunlianBindingConflictError()
        state = await self.tenants.read_external_tenant_state(
            self.source_key(binding.issuer, binding.external_tenant_id)
        )
        if state is None:
            if self.config.auto_onboarding_enabled:
                raise KunlianDirectoryNotReadyError()
            return None
        if state.connection_id != binding.connection_id or state.local_blocked:
            raise KunlianIdentityUnavailableError()
        if state.state != "READY":
            raise KunlianDirectoryNotReadyError()
        mapping = await self.repository.get_tenant_binding(binding.connection_id, binding.external_tenant_id)
        if mapping is None or not mapping.enabled or mapping.local_tenant_id != state.local_tenant_id:
            raise KunlianIdentityUnavailableError()
        return state

    async def current_qualification(self, binding):
        state = await self._tenant_ready(binding)
        if state is None:
            return await self.users.read_current_qualification(binding.local_user_id, identity_key=binding.identity_key)
        try:
            current = await self.access.read_current_qualification(
                binding.local_user_id,
                identity_key=binding.identity_key,
                connection_id=binding.connection_id,
                tenant_id=state.local_tenant_id,
            )
        except KunlianIdentityUnavailableError:
            # 未完成的基础处理只登记恢复需求, 不在登录中创建或授予角色。
            raise KunlianDirectoryNotReadyError() from None
        await self._tenant_ready(binding)
        return current

    async def _provision_tenant(self, facts):
        await self.repository.assert_onboarding_tenant(facts)
        command = ExternalTenantCommand(
            facts.connection_id,
            facts.issuer,
            facts.external_tenant_id,
            facts.display_name,
            facts.batch_id,
            facts.source_revision,
            facts.policy_revision,
            facts.manual_tenant_id,
        )
        previous = await self.tenants.read_external_tenant_state(facts.source_key)
        operation = await self.tenants.reserve_external_tenant(
            command, expected_fence=previous.fence if previous else None
        )
        await self.repository.assert_onboarding_tenant(facts)
        await self.tenants.ensure_external_tenant(command, operation=operation)
        receipt = await self.tenants.read_external_tenant_receipt(operation)
        await self.repository.bind_onboarded_tenant(facts, receipt)

    async def _qualify_member(self, identity_key):
        # 沿用原连接锁和当前来源断言, 不修改原资料投影状态作为资格回执。
        async with self.repository.projection_scope(identity_key, onboarding_policy=self.config) as (
            facts,
            assert_current,
            _,
        ):
            if facts.connection_id != self.config.connection_id or not facts.active or not facts.already_projected:
                raise KunlianDirectoryNotReadyError()
            binding = await self.repository.get_binding(identity_key)
            await self._tenant_ready(binding)
            projection = await self.users.read_current_projection_receipt(identity_key, facts.local_user_id)
            if projection.source_revision != facts.source_revision:
                raise KunlianBindingConflictError()
            template = await self.roles.ensure_external_basic_role(
                await self.roles.reserve_external_basic_role(facts.connection_id, facts.mapping.local_tenant_id)
            )
            command = BasicAccessCommand(
                facts.connection_id,
                identity_key,
                facts.mapping.local_tenant_id,
                facts.local_user_id,
                projection,
                template,
            )
            operation = await self.access.reserve_external_basic_access(command)
            await assert_current()
            await self._tenant_ready(binding)
            await self.access.ensure_external_basic_access(command, operation=operation)
            await assert_current()
            await self._tenant_ready(binding)

    async def recover(self, connection_id, *, stage="tenants", after_key="", limit=25):
        if connection_id != self.config.connection_id or stage not in self.STAGES or not 1 <= limit <= 100:
            raise KunlianTrustRejectedError()
        if not self.config.auto_onboarding_enabled:
            return {"status": "DISABLED", "has_more": False}
        if not self.multi_tenant_enabled:
            raise KunlianDependencyUnavailableError()
        args = {
            "policy_revision": self.config.policy_revision,
            "max_age_seconds": self.config.max_directory_age_seconds,
            "after_key": after_key,
            "limit": limit,
        }
        if stage == "tenants":
            candidates = await self.repository.list_onboarding_tenants(connection_id, issuer=self.config.issuer, **args)
        else:
            # 即使投影成功也独立扫描基础资格, 避免原投影提前返回漏掉用户。
            if stage == "basic_access":
                candidates = await self.repository.list_onboarding_members(connection_id, **args)
            else:
                # 同样先验证完整当前批次, 失效分页不能驱动实际写入。
                await self.repository.list_onboarding_tenants(
                    connection_id,
                    issuer=self.config.issuer,
                    policy_revision=self.config.policy_revision,
                    max_age_seconds=self.config.max_directory_age_seconds,
                    limit=1,
                )
                candidates = await self.repository.list_projection_candidates(
                    connection_id, after_key=after_key, limit=limit
                )
        succeeded = failed = 0
        started = asyncio.get_running_loop().time()
        processed = []
        for candidate in candidates:
            if processed and asyncio.get_running_loop().time() - started >= 240:
                break
            try:
                async with asyncio.timeout(30):
                    if stage == "tenants":
                        await self._provision_tenant(candidate)
                    elif stage == "projection":
                        binding = await self.repository.get_binding(candidate)
                        if binding.admission_status == "ACTIVE":
                            await self._tenant_ready(binding)
                        await self.projection.project_identity(candidate, onboarding_policy=self.config)
                    else:
                        await self._qualify_member(candidate)
                succeeded += 1
            except (KunlianError, TimeoutError) as exc:
                logger.warning(
                    "Kunlian onboarding failed stage={} reason={}",
                    stage,
                    exc.reason_code if isinstance(exc, KunlianError) else "TIMEOUT",
                )
                failed += 1
            processed.append(candidate)
        more = len(processed) < len(candidates) or len(candidates) == limit
        next_index = self.STAGES.index(stage) + 1
        next_stage = stage if more else self.STAGES[next_index] if next_index < len(self.STAGES) else None
        cursor = (processed[-1].external_tenant_id if stage == "tenants" else processed[-1]) if more else ""
        return {
            "succeeded": succeeded,
            "failed": failed,
            "stage": stage,
            "next_stage": next_stage,
            "next_after_key": cursor,
            "has_more": next_stage is not None,
        }

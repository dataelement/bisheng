"""只读 Mock 样例。执行许可和状态由 Workflow SQL 仓储保存。"""

import asyncio
import base64
import binascii
import json
import time

from bisheng.common.errcode.flow import (
    PlatformAgentConfigurationError,
    PlatformAgentExecutionError,
    PlatformAgentPermissionError,
    PlatformAgentUpstreamError,
    PlatformAgentVersionError,
)
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.domain.schemas.platform_agent import (
    AgentInteraction,
    AgentInvokeResult,
    AgentReference,
    AgentRunObservation,
    AgentSubmissionReceipt,
    AgentVersion,
    VerifiedAgentActor,
    canonical_digest,
)

# TODO [F119][EXT-01] 当前资源和 Schema 为 Mock。正式契约确认后替换并运行共享契约验证。
_VERSIONS = {
    "mock:echo": ("v1", "v2"),
    "mock:private": ("v1",),
    "mock:scenario": ("upstream-error", "timeout", "bad-output", "running", "version-mismatch", "disabled"),
    "mock:interaction": ("v1", "v2", "immediate", "lost", "reject"),
}

# TODO [F119][EXT-01] 以下目录名称为本地 Mock 演示数据。正式接入后使用平台返回的名称。
_NAMES = {
    "mock:echo": "通用问答示例 (模拟)",
    "mock:private": "私有 Agent 示例 (模拟)",
    "mock:scenario": "失败与超时示例 (模拟)",
    "mock:interaction": "人工输入示例 (模拟)",
}


class MockPlatformAgentProvider:
    supports_interaction_replay = True

    def __init__(self, config: PlatformAgentConf, *, ledger=None, clock=time.time, enable_interactions=False):
        self.config = config
        self.ledger = ledger
        self.clock = clock
        self.enable_interactions = enable_interactions

    def _label(self, actor: VerifiedAgentActor) -> str:
        # TODO [F119][EXT-02] 此处只模拟外部身份。本地业务授权须由应用入口先完成。
        # 未设置专项 Mock 映射时提供通用 B 样例。实际运行主体不变。
        if not self.config.mock_subjects:
            return "B"
        label = self.config.mock_subjects.get(f"{actor.tenant_id}:{actor.user_id}")
        if label is None:
            raise PlatformAgentPermissionError()
        return label

    async def list_agents(self, actor: VerifiedAgentActor, cursor: str | None = None) -> dict:
        label = self._label(actor)
        scope = canonical_digest([actor.user_id, actor.tenant_id, self.config.model_dump()])
        offset = 0
        if cursor:
            try:
                if len(cursor) > 1024:
                    raise ValueError("cursor")
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                offset = decoded["offset"]
                if decoded["scope"] != scope or type(offset) is not int or offset < 0 or offset > 10000:
                    raise ValueError("cursor")
            except (ValueError, KeyError, TypeError, binascii.Error):
                raise PlatformAgentConfigurationError() from None
        rows = []
        for agent_id, versions in _VERSIONS.items():
            if agent_id == "mock:interaction" and not self.enable_interactions:
                continue
            if label == "C" or (agent_id == "mock:private" and label != "A"):
                continue
            rows.append(
                {
                    "agent_id": agent_id,
                    "name": _NAMES[agent_id],
                    "versions": [version for version in versions if version != "disabled"],
                }
            )
        page = rows[offset : offset + 2]
        next_offset = offset + len(page)
        more = next_offset < len(rows)
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps({"scope": scope, "offset": next_offset}).encode()).decode()
            if more
            else None
        )
        return {
            "data": page,
            "has_more": more,
            "next_cursor": next_cursor,
            "provider_mode": "mock",
            "policy_revision": self.config.policy_revision,
        }

    async def get_version(self, actor: VerifiedAgentActor, ref: AgentReference) -> AgentVersion:
        label = self._label(actor)
        if label == "C" or (ref.agent_id == "mock:private" and label != "A"):
            raise PlatformAgentPermissionError()
        if ref.agent_id == "mock:interaction" and not self.enable_interactions:
            raise PlatformAgentVersionError()
        if ref.version_id not in _VERSIONS.get(ref.agent_id, ()):
            raise PlatformAgentVersionError()
        query_key = "question" if ref.agent_id == "mock:echo" and ref.version_id == "v2" else "query"
        answer_key = "reply" if query_key == "question" else "answer"
        return AgentVersion(
            ref=ref,
            name=_NAMES[ref.agent_id],
            available=ref.version_id != "disabled",
            supports_async=ref.agent_id in {"mock:echo", "mock:interaction"}
            or ref.version_id in {"running", "bad-output", "upstream-error"},
            supports_interaction=ref.agent_id == "mock:interaction",
            input_schema={
                "type": "object",
                "properties": {query_key: {"type": "string"}, "value": {}},
                "required": [query_key],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {answer_key: {"type": "string"}, "viewer": {"type": "string"}, "value": {}},
                "required": [answer_key, "viewer", "value"],
                "additionalProperties": False,
            },
        )

    async def check_use(self, actor: VerifiedAgentActor, ref: AgentReference) -> None:
        version = await self.get_version(actor, ref)
        if not version.available:
            raise PlatformAgentVersionError()

    async def invoke(
        self, actor: VerifiedAgentActor, ref: AgentReference, inputs: dict, call_id: str
    ) -> AgentInvokeResult:
        # TODO [F119][EXT-03] 以下成功及故障结果均为模拟。正式 invoke 到位后补真实联调。
        await self.check_use(actor, ref)
        if ref.version_id == "timeout":
            await asyncio.sleep(self.config.invoke_timeout_seconds + 1)
        if ref.version_id == "upstream-error":
            raise PlatformAgentUpstreamError()
        result_ref = (
            AgentReference(agent_id=ref.agent_id, version_id="unexpected")
            if ref.version_id == "version-mismatch"
            else ref
        )
        query_key = "question" if ref.agent_id == "mock:echo" and ref.version_id == "v2" else "query"
        output = {
            "reply" if query_key == "question" else "answer": inputs[query_key],
            "viewer": self._label(actor),
            "value": inputs.get("value"),
        }
        if ref.version_id == "bad-output":
            output = {"invalid": True}
        return AgentInvokeResult(
            status="RUNNING" if ref.version_id == "running" else "SUCCEEDED",
            ref=result_ref,
            output=output,
            agent_run_id=f"mock:{call_id}",
        )

    async def _store(self):
        return self.ledger if self.ledger is not None else await get_redis_client()

    def _remote_scope(self, actor):
        return [self.config.connection_id, self.config.policy_revision, actor.tenant_id, actor.user_id]

    def _run_id(self, actor, call_id):
        return "mock-async:" + canonical_digest([*self._remote_scope(actor), call_id])

    @staticmethod
    def _key(run_id):
        return f"workflow:f124:mock:{run_id}"

    async def start(self, actor, ref, inputs, call_id):
        # TODO [F124][EXT-01] 用正式异步启动和原关联查回替换模拟账本。
        if not (await self.get_version(actor, ref)).supports_async:
            raise PlatformAgentVersionError()
        run_id = self._run_id(actor, call_id)
        store = await self._store()
        digest = canonical_digest([ref.model_dump(), inputs])
        await store.asetNx(
            self._key(run_id),
            {
                "scope": self._remote_scope(actor),
                "ref": ref.model_dump(),
                "digest": digest,
                "inputs": inputs,
                "accepted": self.clock(),
            },
            expiration=3600,
        )
        record = await self._read(actor, ref, run_id)
        if record["digest"] != digest:
            raise PlatformAgentExecutionError()
        return await self.get_status(actor, ref, run_id)

    async def lookup_start(self, actor, ref, call_id):
        run_id = self._run_id(actor, call_id)
        if await (await self._store()).aget(self._key(run_id)) is None:
            return None
        return await self.get_status(actor, ref, run_id)

    async def _read(self, actor, ref, run_id):
        await self.check_use(actor, ref)
        record = await (await self._store()).aget(self._key(run_id))
        if not record or record["scope"] != self._remote_scope(actor):
            raise PlatformAgentPermissionError()
        if record["ref"] != ref.model_dump():
            raise PlatformAgentExecutionError()
        return record

    async def get_status(self, actor, ref, run_id):
        # TODO [F124][EXT-02] 接入正式状态和结果查询及保留期。
        record = await self._read(actor, ref, run_id)
        cancel = await (await self._store()).aget(f"{self._key(run_id)}:cancel")
        now = self.clock()
        started = record["accepted"]
        interaction = None
        if ref.agent_id == "mock:interaction" and ref.version_id != "immediate":
            submission = await (await self._store()).aget(f"{self._key(run_id)}:submission")
            if not submission or submission["status"] != "ACCEPTED":
                interaction = self._interaction(run_id)
            else:
                started = submission["at"]
        age = now - started
        duration = 90 if ref.version_id == "running" else 3
        cutoff = now if interaction is not None else min(now, started + duration)
        if cancel and cancel["at"] + 1 <= cutoff:
            status = "CANCELLED"
        elif interaction is not None:
            status = "WAITING_INPUT"
        elif age >= duration:
            status = "FAILED" if ref.version_id == "upstream-error" else "SUCCEEDED"
        else:
            status = "RUNNING"
        return AgentRunObservation(
            run_id=run_id,
            ref=ref,
            status=status,
            progress=None if interaction is not None else min(100, max(0, int(age * 100 / duration))),
            interaction=interaction if status == "WAITING_INPUT" else None,
        )

    async def get_result(self, actor, ref, run_id):
        state = await self.get_status(actor, ref, run_id)
        if state.status != "SUCCEEDED":
            return None
        record = await self._read(actor, ref, run_id)
        inputs = record["inputs"]
        if ref.agent_id == "mock:interaction" and ref.version_id != "immediate":
            submission = await (await self._store()).aget(f"{self._key(run_id)}:submission")
            if not submission:
                return None
            inputs = {**inputs, "query": submission["answer"]}
        result = await self.invoke(actor, ref, inputs, run_id)
        return result.model_copy(update={"agent_run_id": run_id, "status": "SUCCEEDED"})

    @staticmethod
    def _interaction(run_id):
        # TODO [F125][EXT-01] 按正式状态契约获取原交互及表单。
        return AgentInteraction(interaction_id=f"{run_id}:input", revision="1", label="补充信息")

    async def _interaction_store(self, actor, ref, run_id, interaction):
        await self._read(actor, ref, run_id)
        original = self._interaction(run_id)
        if (
            ref.agent_id != "mock:interaction"
            or ref.version_id == "immediate"
            or (interaction.interaction_id, interaction.revision) != (original.interaction_id, original.revision)
        ):
            raise PlatformAgentExecutionError()
        return await self._store(), f"{self._key(run_id)}:submission"

    @staticmethod
    def _submission_receipt(ref, run_id, interaction, record):
        return AgentSubmissionReceipt(
            run_id=run_id,
            ref=ref,
            interaction_id=interaction.interaction_id,
            revision=interaction.revision,
            submission_key=record["key"],
            status=record["status"],
        )

    async def submit_interaction(self, actor, ref, run_id, interaction, answer, submission_key):
        # TODO [F125][EXT-02] 按正式幂等和回执查回契约提交。
        store, key = await self._interaction_store(actor, ref, run_id, interaction)
        if (
            interaction != self._interaction(run_id)
            or not submission_key
            or not isinstance(answer, str)
            or not answer.strip()
            or len(answer) > interaction.max_length
        ):
            raise PlatformAgentExecutionError()
        existing = await store.aget(key)
        created = False
        if existing is None:
            if (await self.get_status(actor, ref, run_id)).status == "WAITING_INPUT":
                created = await store.asetNx(
                    key,
                    {
                        "key": submission_key,
                        "answer": answer,
                        "at": self.clock(),
                        "status": "REJECTED" if ref.version_id == "reject" else "ACCEPTED",
                    },
                    expiration=3600,
                )
            existing = await store.aget(key)
        if not existing or existing["key"] != submission_key or existing["answer"] != answer:
            raise PlatformAgentExecutionError()
        if created and ref.version_id == "lost":
            raise TimeoutError()
        return self._submission_receipt(ref, run_id, interaction, existing)

    async def lookup_submission(self, actor, ref, run_id, interaction, submission_key):
        store, key = await self._interaction_store(actor, ref, run_id, interaction)
        record = await store.aget(key)
        if record and record["key"] == submission_key:
            return self._submission_receipt(ref, run_id, interaction, record)
        return None

    async def cancel(self, actor, ref, run_id, cancel_key):
        # TODO [F124][EXT-03] 按正式合同区分取消受理、终态和安全重试。
        state = await self.get_status(actor, ref, run_id)
        if state.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return "TERMINAL"
        key = f"{self._key(run_id)}:cancel"
        store = await self._store()
        await store.asetNx(key, {"id": cancel_key, "at": self.clock()}, expiration=3600)
        return "ACCEPTED" if (await store.aget(key))["id"] == cancel_key else "REJECTED"

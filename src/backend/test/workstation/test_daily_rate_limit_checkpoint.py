from types import SimpleNamespace

import pytest

from bisheng.linsight.domain.services.checkpointer import PlainRedisCheckpointer
from bisheng.llm.domain.services.model_recovery_service import RecoveryNotAllowedError
from bisheng.workstation.domain.services.chat_service import ensure_daily_checkpoint_pending


class FakeAgent:
    def __init__(self, pending: tuple[str, ...]) -> None:
        self.pending = pending
        self.configs = []

    async def aget_state(self, config):
        self.configs.append(config)
        return SimpleNamespace(next=self.pending)


def test_daily_checkpoint_namespace_does_not_change_linsight_legacy_keys() -> None:
    legacy = PlainRedisCheckpointer()
    daily = PlainRedisCheckpointer(namespace="daily")

    assert legacy._ckpt_key("thread-1", "", "checkpoint-1").startswith("linsight:ckpt:data:")
    assert daily._ckpt_key("execution-1", "daily-agent-v1", "checkpoint-1").startswith(
        "daily:ckpt:data:execution-1:daily-agent-v1:"
    )


async def test_recovery_accepts_only_checkpoint_with_pending_node() -> None:
    agent = FakeAgent(("agent",))
    config = {"configurable": {"thread_id": "execution-1"}}

    await ensure_daily_checkpoint_pending(agent, config)

    assert agent.configs == [config]


async def test_missing_or_completed_checkpoint_fails_closed() -> None:
    agent = FakeAgent(())

    with pytest.raises(RecoveryNotAllowedError, match="no pending node"):
        await ensure_daily_checkpoint_pending(
            agent,
            {"configurable": {"thread_id": "execution-1"}},
        )


@pytest.mark.parametrize("namespace", ["", "daily:unsafe"])
def test_checkpoint_namespace_rejects_ambiguous_key_segments(namespace: str) -> None:
    with pytest.raises(ValueError, match="namespace"):
        PlainRedisCheckpointer(namespace=namespace)

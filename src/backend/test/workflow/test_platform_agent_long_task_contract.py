from types import SimpleNamespace

import pytest

from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentPermissionError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.domain.clients.platform_agent_mock import MockPlatformAgentProvider
from bisheng.workflow.domain.schemas.platform_agent import AgentReference, VerifiedAgentActor, node_configuration
from test.workflow.test_platform_agent_node import node_data


class Ledger:
    def __init__(self):
        self.data = {}

    async def asetNx(self, key, value, expiration):
        if key in self.data:
            return False
        self.data[key] = value
        return True

    async def aget(self, key):
        return self.data.get(key)


@pytest.fixture
def long_remote():
    clock = [1000.0]
    ledger = Ledger()
    return SimpleNamespace(
        clock=clock,
        ledger=ledger,
        provider=lambda: MockPlatformAgentProvider(PlatformAgentConf(), ledger=ledger, clock=lambda: clock[0]),
    )


async def test_long_task_contract_is_opt_in_and_remote_keys_survive_adapter_recreation(long_remote):
    assert node_configuration(node_data()).execution_mode == "sync"
    actor = VerifiedAgentActor(12, 7)
    ref = AgentReference(agent_id="mock:echo", version_id="v1")
    provider = long_remote.provider()
    assert (await provider.get_version(actor, ref)).supports_async
    pending = await provider.start(actor, ref, {"query": "hello"}, "one")
    replacement = long_remote.provider()
    assert (await replacement.lookup_start(actor, ref, "one")).run_id == pending.run_id
    assert (await replacement.start(actor, ref, {"query": "hello"}, "one")).run_id == pending.run_id
    with pytest.raises(PlatformAgentExecutionError):
        await replacement.start(actor, ref, {"query": "different"}, "one")
    with pytest.raises(PlatformAgentPermissionError):
        await replacement.get_status(VerifiedAgentActor(11, 7), ref, pending.run_id)
    assert await replacement.cancel(actor, ref, pending.run_id, "stop") == "ACCEPTED"
    assert (await provider.get_status(actor, ref, pending.run_id)).status == "RUNNING"
    long_remote.clock[0] += 1
    assert (await replacement.get_status(actor, ref, pending.run_id)).status == "CANCELLED"

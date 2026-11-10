import pytest

from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentPermissionError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.domain.clients.platform_agent_mock import MockPlatformAgentProvider
from bisheng.workflow.domain.schemas.platform_agent import AgentReference, VerifiedAgentActor, node_configuration
from test.workflow.test_platform_agent_long_task_contract import long_remote as long_remote
from test.workflow.test_platform_agent_node import node_data


def interactive_provider(long_remote, *, clock=None):
    return MockPlatformAgentProvider(
        PlatformAgentConf(),
        ledger=long_remote.ledger,
        clock=clock or (lambda: long_remote.clock[0]),
        enable_interactions=True,
    )


async def test_interaction_is_explicit_and_bound_to_original_remote_run(long_remote):
    assert node_configuration(node_data()).allow_interaction is False
    actor = VerifiedAgentActor(12, 7)
    provider = interactive_provider(long_remote)
    normal_ref = AgentReference(agent_id="mock:echo", version_id="v1")
    ref = AgentReference(agent_id="mock:interaction", version_id="v1")
    assert not (await provider.get_version(actor, normal_ref)).supports_interaction
    assert (await provider.get_version(actor, ref)).supports_interaction

    wait = await provider.start(actor, ref, {"query": "请补充内容"}, "call-1")
    assert wait.status == "WAITING_INPUT" and wait.interaction.required
    other = interactive_provider(long_remote)
    assert await other.lookup_start(actor, ref, "call-1") == wait
    with pytest.raises(PlatformAgentPermissionError):
        await other.submit_interaction(VerifiedAgentActor(11, 7), ref, wait.run_id, wait.interaction, "answer", "key")
    with pytest.raises(PlatformAgentExecutionError):
        await other.submit_interaction(
            actor, ref, wait.run_id, wait.interaction.model_copy(update={"revision": "wrong"}), "answer", "key"
        )
    with pytest.raises(PlatformAgentExecutionError):
        await other.submit_interaction(actor, ref, wait.run_id, wait.interaction, "   ", "key")
    assert await other.lookup_submission(actor, ref, wait.run_id, wait.interaction, "key") is None
    receipt = await other.submit_interaction(actor, ref, wait.run_id, wait.interaction, "answer", "key")
    assert receipt.status == "ACCEPTED" and receipt.run_id == wait.run_id
    assert await provider.lookup_submission(actor, ref, wait.run_id, wait.interaction, "key") == receipt
    assert await provider.submit_interaction(actor, ref, wait.run_id, wait.interaction, "answer", "key") == receipt
    with pytest.raises(PlatformAgentExecutionError):
        await provider.submit_interaction(actor, ref, wait.run_id, wait.interaction, "different", "key")
    with pytest.raises(PlatformAgentExecutionError):
        await provider.submit_interaction(actor, ref, wait.run_id, wait.interaction, "answer", "another")
    assert await other.get_result(actor, ref, wait.run_id) is None
    long_remote.clock[0] += 3
    result = await other.get_result(actor, ref, wait.run_id)
    assert result.agent_run_id == wait.run_id and result.output["answer"] == "answer"


@pytest.mark.parametrize("version_id", ["lost", "reject"])
async def test_mock_submission_distinguishes_lost_receipt_from_rejection(long_remote, version_id):
    actor = VerifiedAgentActor(12, 7)
    provider = interactive_provider(long_remote)
    ref = AgentReference(agent_id="mock:interaction", version_id=version_id)
    wait = await provider.start(actor, ref, {"query": "内容"}, "call")
    arguments = (actor, ref, wait.run_id, wait.interaction, "answer", "key")
    if version_id == "lost":
        with pytest.raises(TimeoutError):
            await provider.submit_interaction(*arguments)
    else:
        assert (await provider.submit_interaction(*arguments)).status == "REJECTED"
    receipt = await interactive_provider(long_remote).lookup_submission(
        actor, ref, wait.run_id, wait.interaction, "key"
    )
    assert receipt.status == ("ACCEPTED" if version_id == "lost" else "REJECTED")

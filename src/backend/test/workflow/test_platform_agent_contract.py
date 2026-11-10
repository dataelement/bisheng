"""覆盖 AC: AC-01, AC-02, AC-04, AC-05, AC-23, AC-24, AC-25。"""

from pathlib import Path

import pytest

from bisheng.common.errcode.flow import (
    PlatformAgentConfigurationError,
    PlatformAgentDisabledError,
    PlatformAgentNotReadyError,
    PlatformAgentPermissionError,
)
from bisheng.core.config.settings import PlatformAgentConf, WorkflowConf
from bisheng.workflow.domain.clients.platform_agent import build_provider
from bisheng.workflow.domain.schemas.platform_agent import (
    MISSING,
    AgentInputBinding,
    AgentReference,
    VerifiedAgentActor,
    resolve_inputs,
    validate_schema,
)


def mock_settings(**changes):
    return PlatformAgentConf(mode="mock", mock_subjects={"7:11": "A", "7:12": "B", "8:13": "C"}, **changes)


@pytest.mark.parametrize(
    "workflow",
    [{}, {"max_steps": 75}, {"platform_agent": {"policy_revision": "custom"}}, {"platform_agent": {"mode": "mock"}}],
)
async def test_default_configuration_shows_mock_agents_and_invokes_without_subject_setup(workflow):
    config = WorkflowConf.model_validate(workflow).platform_agent
    assert config.mode == "mock"
    provider = build_provider(config)
    actor = VerifiedAgentActor(12, 7)
    resources = await provider.list_agents(actor)
    assert resources["provider_mode"] == "mock"
    assert {row["agent_id"] for row in resources["data"]} == {"mock:echo", "mock:scenario"}
    assert next(row for row in resources["data"] if row["agent_id"] == "mock:echo")["name"] == "通用问答示例 (模拟)"
    ref = AgentReference(agent_id="mock:echo", version_id="v1")
    result = await provider.invoke(actor, ref, {"query": "hello", "value": False}, "default-mock")
    assert result.output == {"answer": "hello", "viewer": "B", "value": False}
    with pytest.raises(PlatformAgentPermissionError):
        await provider.get_version(actor, AgentReference(agent_id="mock:private", version_id="v1"))


async def test_explicit_mock_subject_map_rejects_unmapped_users():
    provider = build_provider(mock_settings())
    with pytest.raises(PlatformAgentPermissionError):
        await provider.list_agents(VerifiedAgentActor(99, 7))


async def test_directory_and_execution_follow_the_actual_mock_actor():
    provider = build_provider(mock_settings())
    a, b, c = VerifiedAgentActor(11, 7), VerifiedAgentActor(12, 7), VerifiedAgentActor(13, 8)
    directory = await provider.list_agents(b)
    assert directory["provider_mode"] == "mock"
    assert any(item["agent_id"] == "mock:echo" for item in directory["data"])
    assert not (await provider.list_agents(c))["data"]
    private = AgentReference(agent_id="mock:private", version_id="v1")
    await provider.get_version(a, private)
    with pytest.raises(PlatformAgentPermissionError):
        await provider.get_version(b, private)
    ref = AgentReference(agent_id="mock:echo", version_id="v1")
    result = await provider.invoke(b, ref, {"query": "hello", "value": 0}, "fixture-call")
    assert result.status == "SUCCEEDED" and result.ref == ref
    assert result.output == {"answer": "hello", "viewer": "B", "value": 0}


async def test_cursor_is_bound_to_the_user_tenant_and_policy_revision():
    provider = build_provider(mock_settings())
    actor = VerifiedAgentActor(11, 7)
    first = await provider.list_agents(actor)
    cursor = first["next_cursor"]
    assert cursor and first["has_more"]
    assert (await provider.list_agents(actor, cursor))["data"][0]["agent_id"] == "mock:scenario"
    with pytest.raises(PlatformAgentConfigurationError):
        await provider.list_agents(VerifiedAgentActor(12, 7), cursor)
    with pytest.raises(PlatformAgentConfigurationError):
        await build_provider(mock_settings(policy_revision="mock-v2")).list_agents(actor, cursor)


@pytest.mark.parametrize("mode,error", [("disabled", PlatformAgentDisabledError), ("real", PlatformAgentNotReadyError)])
def test_unavailable_sources_do_not_fall_back_to_mock(mode, error):
    with pytest.raises(error):
        build_provider(PlatformAgentConf(mode=mode))


@pytest.mark.parametrize("value", [0, False, "", None, [1, {"x": False}], {"a": [1]}])
def test_mapping_preserves_json_values_and_distinguishes_missing(value):
    schema = {"type": "object", "properties": {"x": {}}, "required": ["x"]}
    bindings = {"x": AgentInputBinding(source="variable", variable="start.x")}
    assert resolve_inputs(bindings, schema, lambda _: value) == {"x": value}
    with pytest.raises(PlatformAgentConfigurationError):
        resolve_inputs(bindings, schema, lambda _: MISSING)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"x": {"$ref": "https://fixture.invalid/schema"}}},
        {"type": "object", "anyOf": [{"required": ["a"]}]},
        {"type": "object", "properties": {"x": {"format": "secret-format"}}},
    ],
)
def test_unimplemented_schema_constraints_are_rejected(schema):
    with pytest.raises(PlatformAgentConfigurationError):
        validate_schema(schema, root_object=True)


def test_mapping_rejects_an_incompatible_new_version_without_coercion():
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    with pytest.raises(PlatformAgentConfigurationError):
        resolve_inputs({"x": AgentInputBinding(source="constant", value="12")}, schema, lambda _: MISSING)


def test_mock_and_real_placeholder_keep_the_replacement_markers():
    root = Path(__file__).parents[2] / "bisheng/workflow/domain/clients"
    text = "\n".join((root / name).read_text() for name in ("platform_agent.py", "platform_agent_mock.py"))
    for external in ("EXT-01", "EXT-02", "EXT-03"):
        assert f"# TODO [F119][{external}]" in text

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantExecutorNotFoundError,
    ResourceGrantVerificationResult,
)
from bisheng.permission.domain.services.resource_grant_executor_registry import (
    ResourceGrantExecutorRegistry,
)

REQUIRED_RESOURCE_TYPES = {"knowledge_space", "channel"}


class _Executor:
    def __init__(self, resource_type: str) -> None:
        self.resource_type = resource_type
        self.execute_calls: list[ResourceGrantCommand] = []
        self.verify_calls: list[ResourceGrantCommand] = []

    async def execute(self, command: ResourceGrantCommand) -> None:
        self.execute_calls.append(command)

    async def verify(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult:
        self.verify_calls.append(command)
        return ResourceGrantVerificationResult(
            applied=True,
            result_snapshot={
                "request_id": command.request_id,
                "resource_type": self.resource_type,
            },
        )


def _command(*, resource_type: str) -> ResourceGrantCommand:
    return ResourceGrantCommand(
        tenant_id=7,
        request_id=301,
        request_fingerprint="request-fingerprint",
        resource_type=resource_type,
        resource_id="resource-901",
        inviter_user_id=11,
        target_user_id=12,
        relation="editor",
        model_id="model-1",
        include_children=True,
        role_snapshot={"role": "editor", "scope": "subtree"},
        role_fingerprint="role-fingerprint",
    )


def _complete_registry() -> tuple[
    ResourceGrantExecutorRegistry,
    _Executor,
    _Executor,
]:
    registry = ResourceGrantExecutorRegistry()
    knowledge_executor = _Executor("knowledge_space")
    channel_executor = _Executor("channel")
    registry.register("knowledge_space", knowledge_executor)
    registry.register("channel", channel_executor)
    registry.freeze(required_resource_types=REQUIRED_RESOURCE_TYPES)
    return registry, knowledge_executor, channel_executor


async def test_registry_registers_and_routes_each_resource_owner_executor() -> None:
    registry, knowledge_executor, channel_executor = _complete_registry()
    knowledge_command = _command(resource_type="knowledge_space")
    channel_command = _command(resource_type="channel")

    await registry.execute(knowledge_command)
    verification = await registry.verify(channel_command)

    assert knowledge_executor.execute_calls == [knowledge_command]
    assert knowledge_executor.verify_calls == []
    assert channel_executor.execute_calls == []
    assert channel_executor.verify_calls == [channel_command]
    assert verification == ResourceGrantVerificationResult(
        applied=True,
        result_snapshot={
            "request_id": channel_command.request_id,
            "resource_type": "channel",
        },
    )


def test_grant_command_and_verification_result_are_stable_immutable_values() -> None:
    command = _command(resource_type="knowledge_space")
    verification = ResourceGrantVerificationResult(
        applied=False,
        result_snapshot={"reason": "grant_not_visible"},
    )

    assert command.request_id == 301
    assert command.request_fingerprint == "request-fingerprint"
    assert command.role_fingerprint == "role-fingerprint"
    assert verification.applied is False
    with pytest.raises(FrozenInstanceError):
        command.resource_id = "changed"
    with pytest.raises(FrozenInstanceError):
        verification.applied = True


def test_dto_snapshots_are_detached_and_deeply_read_only() -> None:
    role_source = {"scope": {"resource_ids": ["one"]}}
    result_source = {"grants": [{"relation": "editor"}]}
    command = replace(
        _command(resource_type="knowledge_space"),
        role_snapshot=role_source,
    )
    verification = ResourceGrantVerificationResult(
        applied=True,
        result_snapshot=result_source,
    )

    role_source["scope"]["resource_ids"].append("two")
    result_source["grants"][0]["relation"] = "owner"

    assert command.role_snapshot["scope"]["resource_ids"] == ("one",)
    assert verification.result_snapshot["grants"][0]["relation"] == "editor"
    with pytest.raises(TypeError):
        command.role_snapshot["scope"]["resource_ids"] = ("changed",)
    with pytest.raises(TypeError):
        verification.result_snapshot["grants"][0]["relation"] = "changed"


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("tenant_id", 0),
        ("request_id", -1),
        ("inviter_user_id", True),
        ("target_user_id", 0),
        ("request_fingerprint", " "),
        ("resource_type", ""),
        ("resource_id", "\t"),
        ("relation", " "),
        ("role_fingerprint", ""),
    ],
)
def test_grant_command_rejects_untrusted_required_values(
    field_name: str,
    invalid_value: object,
) -> None:
    command = _command(resource_type="knowledge_space")

    with pytest.raises(ValueError, match=field_name):
        replace(command, **{field_name: invalid_value})


def test_grant_command_normalizes_required_text_before_dispatch() -> None:
    command = replace(
        _command(resource_type="knowledge_space"),
        request_fingerprint=" request-fingerprint ",
        resource_type=" knowledge_space ",
        resource_id=" resource-901 ",
        relation=" editor ",
        role_fingerprint=" role-fingerprint ",
    )

    assert command.request_fingerprint == "request-fingerprint"
    assert command.resource_type == "knowledge_space"
    assert command.resource_id == "resource-901"
    assert command.relation == "editor"
    assert command.role_fingerprint == "role-fingerprint"


def test_duplicate_resource_type_registration_fails_startup() -> None:
    registry = ResourceGrantExecutorRegistry()
    registry.register("knowledge_space", _Executor("knowledge_space"))

    with pytest.raises(ValueError, match="already registered") as error:
        registry.register("knowledge_space", _Executor("knowledge_space"))
    assert "knowledge_space" in str(error.value)


def test_missing_required_resource_type_fails_freeze() -> None:
    registry = ResourceGrantExecutorRegistry()
    registry.register("knowledge_space", _Executor("knowledge_space"))

    with pytest.raises(ValueError, match="missing") as error:
        registry.freeze(required_resource_types=REQUIRED_RESOURCE_TYPES)
    assert "channel" in str(error.value)


def test_repeated_freeze_still_checks_new_required_types() -> None:
    registry, _, _ = _complete_registry()

    with pytest.raises(ValueError, match="missing") as error:
        registry.freeze(required_resource_types=REQUIRED_RESOURCE_TYPES | {"workflow"})
    assert "workflow" in str(error.value)


@pytest.mark.parametrize("operation", ["execute", "verify"])
async def test_unknown_resource_type_fails_closed(operation: str) -> None:
    registry, knowledge_executor, channel_executor = _complete_registry()
    command = _command(resource_type="workflow")

    with pytest.raises(ResourceGrantExecutorNotFoundError, match="workflow"):
        await getattr(registry, operation)(command)

    assert knowledge_executor.execute_calls == []
    assert knowledge_executor.verify_calls == []
    assert channel_executor.execute_calls == []
    assert channel_executor.verify_calls == []


def test_freeze_rejects_later_registration() -> None:
    registry, _, _ = _complete_registry()

    with pytest.raises(RuntimeError, match="frozen"):
        registry.register("workflow", _Executor("workflow"))


def test_registry_does_not_import_resource_owner_implementations() -> None:
    registry_path = (
        Path(__file__).resolve().parents[2]
        / "bisheng"
        / "permission"
        / "domain"
        / "services"
        / "resource_grant_executor_registry.py"
    )
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    imported_references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_references.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_references.add(node.module)
            imported_references.update(f"{node.module}.{alias.name}" for alias in node.names)

    forbidden_owner_suffixes = {
        "resource_authorization_service",
        "channel_authorization_service",
    }
    assert not any(
        reference.rsplit(".", maxsplit=1)[-1] in forbidden_owner_suffixes for reference in imported_references
    )
    assert not any(
        reference.startswith(("bisheng.channel.", "bisheng.knowledge.")) for reference in imported_references
    )

"""Contracts for ordinary Grants immediately after resource creation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.permission.application.initial_grant import (
    InitialGrantAddition,
    InitialGrantApplication,
    InitialGrantRequest,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def allocate_source_ids(self, count: int):
        self.calls.append(("allocate", count))
        return tuple(range(91, 91 + count))

    async def mutate_grants(self, **kwargs):
        self.calls.append(("mutate", kwargs))
        return SimpleNamespace(resource_version=2, grants=kwargs["changes"])


class _Subjects:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.sources = GrantSourceService()

    async def canonical_source(self, **kwargs):
        self.calls.append(kwargs)
        source_types = {
            "user": "DIRECT",
            "department": "DEPARTMENT",
            "user_group": "USER_GROUP",
        }
        return self.sources.canonicalize_source(
            source_id=kwargs["source_id"],
            subject_type=kwargs["subject_type"],
            subject_id=kwargs["subject_id"],
            userset_relation=kwargs["userset_relation"],
            include_children=kwargs["include_children"],
            source_type=source_types[kwargs["subject_type"]],
        )


def _target() -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="101",
        resource_version=1,
        context_version="knowledge-space:101:v1",
    )


def _actor() -> PermissionActor:
    return PermissionActor(user_id=11, current_tenant_id=7)


async def test_additions_are_canonicalized_and_sent_to_f048_mutation() -> None:
    runtime = _Runtime()
    subjects = _Subjects()
    service = InitialGrantApplication(runtime=runtime, subjects=subjects)
    request = InitialGrantRequest(
        command_key="create-request-1",
        expected_catalog_release_id=42,
        additions=(
            InitialGrantAddition(model_key="viewer", subject_type="user", subject_id="8"),
            InitialGrantAddition(
                model_key="editor",
                subject_type="department",
                subject_id="5",
                userset_relation="subtree_member",
                include_children=True,
            ),
        ),
    )

    result = await service.apply(actor=_actor(), target=_target(), request=request)

    assert result.resource_version == 2
    assert runtime.calls[0] == ("allocate", 2)
    mutation = runtime.calls[1][1]
    assert mutation["actor"] == _actor()
    assert mutation["target"] == _target()
    assert mutation["expected_resource_version"] == 1
    assert mutation["expected_catalog_release_id"] == 42
    assert mutation["idempotency_key"].startswith("f050:initial-grants:")
    assert len(mutation["idempotency_key"]) <= 64
    assert [change.operation for change in mutation["changes"]] == ["ADD", "ADD"]
    assert [change.model_key for change in mutation["changes"]] == ["viewer", "editor"]
    assert [change.source.source_type for change in mutation["changes"]] == [
        "DIRECT",
        "DEPARTMENT",
    ]
    assert all(change.source.protected is False for change in mutation["changes"])
    assert [call["tenant_id"] for call in subjects.calls] == [7, 7]


async def test_command_key_derives_a_stable_target_scoped_idempotency_key() -> None:
    runtime = _Runtime()
    service = InitialGrantApplication(runtime=runtime, subjects=_Subjects())
    request = InitialGrantRequest(
        command_key="create-request-1",
        expected_catalog_release_id=42,
        additions=(InitialGrantAddition(model_key="viewer", subject_type="user", subject_id="8"),),
    )

    await service.apply(actor=_actor(), target=_target(), request=request)
    first = runtime.calls[-1][1]["idempotency_key"]
    await service.apply(actor=_actor(), target=_target(), request=request)
    second = runtime.calls[-1][1]["idempotency_key"]

    assert first == second


@pytest.mark.parametrize(
    "initial_request",
    [
        InitialGrantRequest(command_key="key", expected_catalog_release_id=42, additions=()),
        InitialGrantRequest(
            command_key="key",
            expected_catalog_release_id=42,
            additions=(object(),),
        ),
    ],
)
async def test_only_non_empty_typed_additions_are_accepted(initial_request) -> None:
    runtime = _Runtime()
    service = InitialGrantApplication(runtime=runtime, subjects=_Subjects())

    with pytest.raises((TypeError, ValueError)):
        await service.apply(actor=_actor(), target=_target(), request=initial_request)

    assert runtime.calls == []


async def test_verified_target_is_mandatory() -> None:
    runtime = _Runtime()
    service = InitialGrantApplication(runtime=runtime, subjects=_Subjects())
    request = InitialGrantRequest(
        command_key="key",
        expected_catalog_release_id=42,
        additions=(InitialGrantAddition(model_key="viewer", subject_type="user", subject_id="8"),),
    )

    with pytest.raises(TypeError, match="VerifiedPermissionTarget"):
        await service.apply(actor=_actor(), target=object(), request=request)

    assert runtime.calls == []

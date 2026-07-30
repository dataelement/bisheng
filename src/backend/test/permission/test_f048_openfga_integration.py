"""Real OpenFGA v1.15.1 integration contract for F048.

The suite is intentionally environment-gated.  CI must start a disposable
``openfga/openfga:v1.15.1`` container by digest, write its inspect metadata to
``F048_OPENFGA_RUNTIME_METADATA``, and set ``F048_OPENFGA_INTEGRATION=1``.
The tests create and delete only their own Store.

覆盖 AC: AC-22, AC-23, AC-28, AC-30, AC-33, AC-34, AC-37, AC-38,
AC-46, AC-47, AC-54, AC-69, AC-109, AC-111, AC-112, AC-114
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.exceptions import FGAClientError, FGAWriteError

pytestmark = pytest.mark.skipif(
    os.environ.get("F048_OPENFGA_INTEGRATION") != "1",
    reason=("requires disposable OpenFGA v1.15.1; set F048_OPENFGA_INTEGRATION=1"),
)

EXPECTED_IMAGE = "openfga/openfga:v1.15.1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OpenFGARuntime:
    api_url: str
    store_id: str
    old_model_id: str
    model_id: str
    client: FGAClient
    old_client: FGAClient
    resolve_node_limit: int


def _runtime_metadata() -> dict:
    path_value = os.environ.get("F048_OPENFGA_RUNTIME_METADATA")
    if not path_value:
        pytest.fail("F048_OPENFGA_RUNTIME_METADATA is required when integration is enabled")
    path = Path(path_value)
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        pytest.fail(f"invalid OpenFGA runtime metadata: {exc}")
    assert metadata["image"] == EXPECTED_IMAGE
    assert _DIGEST.fullmatch(metadata["image_digest"])
    assert metadata["version"] == "1.15.1"
    assert int(metadata["resolve_node_limit"]) >= 8
    return metadata


def _legacy_model() -> dict:
    return {
        "schema_version": "1.1",
        "type_definitions": [
            {"type": "user", "relations": {}, "metadata": None},
            {
                "type": "workflow",
                "relations": {"viewer": {"this": {}}},
                "metadata": {"relations": {"viewer": {"directly_related_user_types": [{"type": "user"}]}}},
            },
        ],
    }


async def _create_store(http: httpx.AsyncClient) -> str:
    response = await http.post("/stores", json={"name": "f048-integration"})
    response.raise_for_status()
    return str(response.json()["id"])


@pytest.fixture(scope="module")
async def openfga_runtime():
    metadata = _runtime_metadata()
    api_url = os.environ.get("F048_OPENFGA_API_URL", "http://127.0.0.1:8080")
    async with httpx.AsyncClient(
        base_url=api_url.rstrip("/"),
        timeout=httpx.Timeout(30),
    ) as http:
        health = await http.get("/healthz")
        health.raise_for_status()
        assert health.json()["status"] == "SERVING"
        store_id = await _create_store(http)
        bootstrap = FGAClient(
            api_url=api_url,
            store_id=store_id,
            model_id="bootstrap-model",
            timeout=30,
        )
        old_client = None
        client = None
        try:
            old_model_id = await bootstrap.write_authorization_model(_legacy_model())
            old_client = bootstrap.for_model(old_model_id)
            model = build_authorization_model_f048()
            model_id = await bootstrap.write_authorization_model(model)
            client = bootstrap.for_model(model_id)
            yield OpenFGARuntime(
                api_url=api_url,
                store_id=store_id,
                old_model_id=old_model_id,
                model_id=model_id,
                client=client,
                old_client=old_client,
                resolve_node_limit=int(metadata["resolve_node_limit"]),
            )
        finally:
            if client is not None:
                await client.close()
            if old_client is not None:
                await old_client.close()
            await bootstrap.close()
            # Exact cleanup of the disposable Store created by this fixture.
            cleanup = await http.delete(f"/stores/{store_id}")
            assert cleanup.status_code in {200, 204}


def _release_tuples() -> list[dict[str, str]]:
    return [
        {
            "user": "user:*",
            "relation": "active",
            "object": "permission_catalog_release:integration",
        },
        {
            "user": "permission_catalog_release:integration",
            "relation": "catalog",
            "object": "permission_model_release:integration",
        },
        {
            "user": "user:*",
            "relation": "enabled_marker",
            "object": "permission_model_release:integration",
        },
        {
            "user": "user:*",
            "relation": "use_marker",
            "object": "permission_model_release:integration",
        },
        {
            "user": "user:*",
            "relation": "download_marker",
            "object": "permission_model_release:integration",
        },
        {
            "user": "permission_model_release:integration",
            "relation": "release",
            "object": "permission_model:integration",
        },
    ]


def _resource_grant(
    *,
    resource: str,
    grant_id: str,
    assignee: str,
    custom: bool = True,
) -> list[dict[str, str]]:
    tuples = [
        {
            "user": "permission_model:integration",
            "relation": "model",
            "object": f"permission_grant:{grant_id}",
        },
        {
            "user": assignee,
            "relation": "ordinary_assignee",
            "object": f"permission_grant:{grant_id}",
        },
        {
            "user": f"permission_grant:{grant_id}",
            "relation": "grant",
            "object": resource,
        },
        {
            "user": "user:*",
            "relation": "permission_enabled",
            "object": resource,
        },
    ]
    if custom:
        tuples.append(
            {
                "user": "user:*",
                "relation": "custom_mode",
                "object": resource,
            }
        )
    return tuples


async def test_same_store_single_new_model_and_model_checksum(
    openfga_runtime: OpenFGARuntime,
) -> None:
    runtime = openfga_runtime
    assert runtime.old_client.store_id == runtime.client.store_id == runtime.store_id
    assert runtime.old_model_id != runtime.model_id
    models = await runtime.client.list_authorization_models()
    ids = {str(item["id"]) for item in models}
    assert {runtime.old_model_id, runtime.model_id}.issubset(ids)

    async with httpx.AsyncClient(
        base_url=runtime.api_url,
        timeout=httpx.Timeout(30),
    ) as http:
        response = await http.get(f"/stores/{runtime.store_id}/authorization-models/{runtime.model_id}")
        response.raise_for_status()
        value = response.json().get("authorization_model", response.json())
        live_model = {
            "schema_version": value["schema_version"],
            "type_definitions": value["type_definitions"],
        }
    assert authorization_model_checksum(live_model) == authorization_model_checksum(build_authorization_model_f048())


async def test_real_check_batch_list_and_higher_consistency_semantics(
    openfga_runtime: OpenFGARuntime,
) -> None:
    client = openfga_runtime.client
    tuples = _release_tuples()
    tuples.extend(
        _resource_grant(
            resource="workflow:direct",
            grant_id="direct",
            assignee="user:1",
        )
    )
    tuples.extend(
        (
            {
                "user": "user:2",
                "relation": "member",
                "object": "department:engineering",
            },
        )
    )
    tuples.extend(
        _resource_grant(
            resource="workflow:department",
            grant_id="department",
            assignee="department:engineering#member",
        )
    )
    tuples.extend(
        (
            {
                "user": "user:3",
                "relation": "member",
                "object": "user_group:reviewers",
            },
        )
    )
    tuples.extend(
        _resource_grant(
            resource="workflow:group",
            grant_id="group",
            assignee="user_group:reviewers#member",
        )
    )
    tuples.extend(
        _resource_grant(
            resource="knowledge_space:parent",
            grant_id="parent",
            assignee="user:4",
        )
    )
    tuples.extend(
        (
            {
                "user": "user:*",
                "relation": "permission_enabled",
                "object": "knowledge_file:child",
            },
            {
                "user": "user:*",
                "relation": "inherit_mode",
                "object": "knowledge_file:child",
            },
            {
                "user": "knowledge_space:parent",
                "relation": "parent",
                "object": "knowledge_file:child",
            },
        )
    )
    await client.write_tuples(writes=tuples)

    assert await client.check(
        "user:1",
        "can_use",
        "workflow:direct",
        consistency="HIGHER_CONSISTENCY",
    )
    assert await client.check(
        "user:2",
        "can_use",
        "workflow:department",
        consistency="HIGHER_CONSISTENCY",
    )
    assert await client.check(
        "user:3",
        "can_use",
        "workflow:group",
        consistency="HIGHER_CONSISTENCY",
    )
    assert await client.check(
        "user:4",
        "can_download",
        "knowledge_file:child",
        consistency="HIGHER_CONSISTENCY",
    )
    assert await client.batch_check(
        [
            {
                "user": "user:1",
                "relation": "can_use",
                "object": "workflow:direct",
            },
            {
                "user": "user:1",
                "relation": "can_use",
                "object": "workflow:department",
            },
        ],
        consistency="HIGHER_CONSISTENCY",
    ) == [True, False]
    assert await client.list_objects(
        "user:1",
        "can_use",
        "workflow",
        consistency="HIGHER_CONSISTENCY",
    ) == ["workflow:direct"]


async def test_store_scoped_legacy_delete_with_new_model(
    openfga_runtime: OpenFGARuntime,
) -> None:
    legacy = {
        "user": "user:9",
        "relation": "viewer",
        "object": "workflow:legacy",
    }
    await openfga_runtime.old_client.write_tuples(writes=[legacy])
    assert await openfga_runtime.old_client.read_tuples(
        user=legacy["user"],
        relation=legacy["relation"],
        object=legacy["object"],
        consistency="HIGHER_CONSISTENCY",
    ) == [legacy]
    await openfga_runtime.client.delete_tuples_store_scoped([legacy])
    assert (
        await openfga_runtime.old_client.read_tuples(
            user=legacy["user"],
            relation=legacy["relation"],
            object=legacy["object"],
            consistency="HIGHER_CONSISTENCY",
        )
        == []
    )


async def test_failed_atomic_write_leaves_no_partial_tuple(
    openfga_runtime: OpenFGARuntime,
) -> None:
    valid = {
        "user": "user:77",
        "relation": "member",
        "object": "user_group:atomic",
    }
    invalid = {
        "user": "user:77",
        "relation": "relation_does_not_exist",
        "object": "user_group:atomic",
    }
    with pytest.raises(FGAWriteError):
        await openfga_runtime.client.write_tuples(writes=[valid, invalid])
    assert (
        await openfga_runtime.client.read_tuples(
            user=valid["user"],
            relation=valid["relation"],
            object=valid["object"],
            consistency="HIGHER_CONSISTENCY",
        )
        == []
    )


async def _write_department_chain(
    client: FGAClient,
    *,
    prefix: str,
    depth: int,
) -> tuple[str, str]:
    root = f"department:{prefix}-0"
    tuples = []
    for index in range(depth):
        parent = f"department:{prefix}-{index}"
        child = f"department:{prefix}-{index + 1}"
        tuples.append({"user": child, "relation": "child", "object": parent})
    leaf = f"department:{prefix}-{depth}"
    tuples.append({"user": "user:88", "relation": "member", "object": leaf})
    for offset in range(0, len(tuples), 90):
        await client.write_tuples(writes=tuples[offset : offset + 90])
    return root, leaf


async def test_pinned_max_resolve_depth_is_exercised(
    openfga_runtime: OpenFGARuntime,
) -> None:
    client = openfga_runtime.client
    safe_depth = max(2, openfga_runtime.resolve_node_limit // 3)
    root, _ = await _write_department_chain(
        client,
        prefix="safe",
        depth=safe_depth,
    )
    assert await client.check(
        "user:88",
        "subtree_member",
        root,
        consistency="HIGHER_CONSISTENCY",
    )

    over_depth = openfga_runtime.resolve_node_limit + 2
    too_deep_root, _ = await _write_department_chain(
        client,
        prefix="too-deep",
        depth=over_depth,
    )
    with pytest.raises(FGAClientError):
        await client.check(
            "user:88",
            "subtree_member",
            too_deep_root,
            consistency="HIGHER_CONSISTENCY",
        )

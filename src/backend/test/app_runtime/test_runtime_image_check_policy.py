"""F119 覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32, AC-34: server-side checker scope."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_image_check_policy import frozen_targets, registry_sources
from bisheng.app_runtime.domain.services.runtime_kubernetes_service import RuntimeKubernetesService


def case():
    helper = "helper.invalid/helper@sha256:" + "a" * 64
    runtime = "registry.invalid/runtime@sha256:" + "b" * 64
    profile = {"runtime_image": runtime, "runtime_image_id": "sha256:" + "c" * 64}
    node = SimpleNamespace(
        id="node",
        executor_kind="kubernetes",
        platform="linux/amd64",
        capabilities={"helper_image": helper, "image_check_registry_secret": "registry-auth"},
    )
    op = SimpleNamespace(
        id="op", kind="deploy", node_id="node", payload={"resolved_delivery": {"mode": "bundle", "profile": profile}}
    )
    document = {"platform": node.platform, "targets": frozen_targets(op, node)}
    env = {
        "IMAGE_CHECK_PLAN": json.dumps(document, sort_keys=True, separators=(",", ":")),
        "DOCKER_CONFIG": "/run/registry",
    }
    spec = {
        "activeDeadlineSeconds": 120,
        "containers": [
            {
                "name": "image-check",
                "image": helper,
                "command": ["python", "-I", "-m", "runtime_manager.image_check"],
                "env": [{"name": k, "value_sha256": hashlib.sha256(v.encode()).hexdigest()} for k, v in env.items()],
                "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
            }
        ],
        "initContainers": [],
        "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}}],
    }
    return op, node, spec


def test_fixed_roles_and_sources_do_not_include_application_egress_or_assembler():
    op, node, spec = case()
    op.payload["egress_domains"] = ["attacker.invalid"]
    RuntimeKubernetesService._validate_image_check(spec, op, node, [])
    assert [t["role"] for t in frozen_targets(op, node)] == ["helper", "runtime"]
    assert registry_sources(op, node) == ["https://helper.invalid:443", "https://registry.invalid:443"]
    assert "assembler" not in json.dumps(frozen_targets(op, node))


@pytest.mark.parametrize(
    "changed", ["target", "command", "image", "source-mount", "init", "credentials", "timeout", "claim", "secret"]
)
def test_even_an_approved_plan_cannot_escape_checker_scope(changed):
    op, node, spec = case()
    container = spec["containers"][0]
    claims = []
    if changed == "target":
        container["env"][0]["value_sha256"] = "0" * 64
    if changed == "command":
        container["command"] = ["sh", "-c", "untrusted"]
    if changed == "image":
        container["image"] = op.payload["resolved_delivery"]["profile"]["runtime_image"]
    if changed == "source-mount":
        container["volumeMounts"].append({"mountPath": "/workspace/app"})
    if changed == "init":
        spec["initContainers"].append({"name": "untrusted"})
    if changed == "credentials":
        container["env"].append({"name": "BISHENG_APP_TOKEN", "value_sha256": "0" * 64})
    if changed == "timeout":
        spec["activeDeadlineSeconds"] = 1800
    if changed == "claim":
        claims = ["data-app"]
    if changed == "secret":
        spec["volumes"].append({"name": "registry-auth", "secret": {"secretName": "business-secrets"}})
    with pytest.raises(RuntimeConflict):
        RuntimeKubernetesService._validate_image_check(spec, op, node, claims)


async def test_registry_policy_denies_arbitrary_sources_before_issuing_any_handle():
    from bisheng.app_runtime.domain.services.runtime_egress_service import RuntimeEgressService

    op, node, _ = case()
    repo = SimpleNamespace(get=AsyncMock(return_value=node), find=AsyncMock())
    with pytest.raises(RuntimeConflict, match="registry_scope"):
        await RuntimeEgressService(repo).issue(op, phase="image-check", package_sources=["https://attacker.invalid"])
    repo.find.assert_not_awaited()


def test_http_private_registry_is_explicit_and_other_origins_stay_tls():
    from bisheng.app_runtime.domain.services.runtime_image_check_policy import check_document

    op, node, _ = case()
    node.capabilities.update(insecure_registry=True, image_repository="registry.invalid/apps")
    assert check_document(op, node)["insecure_registries"] == ["registry.invalid"]
    assert registry_sources(op, node) == ["http://registry.invalid:80", "https://helper.invalid:443"]


@pytest.mark.parametrize(
    "kind,mode",
    [
        ("prepare", "bundle"),
        ("prepare", "image"),
        ("prepare", "source-image"),
        ("deploy", "bundle"),
        ("deploy", "image"),
        ("deploy", "source-image"),
    ],
)
@pytest.mark.parametrize("insecure", [False, True])
def test_backend_target_document_matches_the_actual_standalone_manager(kind, mode, insecure):
    import subprocess
    import sys
    from pathlib import Path

    from bisheng.app_runtime.domain.services.runtime_image_check_policy import check_document

    op, node, _ = case()
    op.kind = kind
    profile = op.payload["resolved_delivery"]["profile"]
    profile.update(preparer_image="preparer.invalid/tools@sha256:" + "d" * 64, preparer_image_id="sha256:" + "e" * 64)
    delivery = {
        "mode": mode,
        "profile": profile,
        "image": "registry.invalid/image@sha256:" + "f" * 64,
        "image_ref": "registry.invalid/image@sha256:" + "f" * 64,
    }
    op.payload.update(delivery=delivery, profile=profile, resolved_delivery=delivery)
    node.capabilities.update(
        assembler_image="assembler.invalid/tool@sha256:" + "f" * 64,
        image_repository="registry.invalid/apps",
        insecure_registry=insecure,
    )
    document = {
        "operation": {"kind": kind, "payload": op.payload},
        "capabilities": node.capabilities,
        "platform": node.platform,
    }
    manager = Path(__file__).resolve().parents[4] / "src/runtime-manager"
    script = "import sys,json; sys.path.insert(0,sys.argv[1]); from runtime_manager.image_check import check_document; d=json.load(sys.stdin); print(json.dumps(check_document(d['operation'],d['capabilities'],d['platform']),sort_keys=True))"
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(manager)],
        input=json.dumps(document),
        text=True,
        check=True,
        capture_output=True,
    )
    assert json.loads(result.stdout) == check_document(op, node)

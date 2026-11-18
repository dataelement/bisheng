"""Scoped recreation exports only selected services with plaintext credential mounts."""

import json

from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.credential_rotation_compose import compile_native
from test.core.test_credential_sealed_bundle import sealed_deployment as sealed_deployment
from test.deploy.test_rotation_compose import inventory as inventory


def test_plaintext_recreation_exports_only_selected_services(sealed_deployment, inventory):
    args, _ = sealed_deployment
    base = prepare_bundle(**args)
    assert json.loads((base / "manifest.json").read_text())["native_storage"] == "plaintext"
    # Option C inventories do not carry sealed_runtime; compile must still work.
    inventory.pop("sealed_runtime", None)
    result = compile_native(
        inventory, component="mysql", bundle=str(base), installer_root="/new/docker", secret_gid="20", run_id="a" * 32
    )
    assert set(result["compose"]["services"]) == {"mysql", "openfga"}
    assert "old-value" not in json.dumps(result["compose"])
    for service in result["compose"]["services"].values():
        assert all(".sealed.json" not in str(v) for v in service.get("volumes", []))
        assert all("bisheng-credential-runtime" not in str(v) for v in service.get("volumes", []))
    mysql = result["compose"]["services"]["mysql"]
    assert mysql["entrypoint"] == ["bash", "/credential-entrypoint.sh"]
    assert any(
        isinstance(v, dict) and v.get("target") == "/run/secrets/mysql.password" for v in mysql["volumes"]
    ) or any("mysql.password:/run/secrets/mysql.password:ro" in str(v) for v in mysql["volumes"])


def test_plaintext_recreation_preserves_milvus_resources_without_sealed_tmpfs(sealed_deployment, inventory):
    args, _ = sealed_deployment
    base = prepare_bundle(**args)
    inventory.pop("sealed_runtime", None)
    result = compile_native(
        inventory, component="minio", bundle=str(base), installer_root="/new/docker", secret_gid="20", run_id="b" * 32
    )
    assert set(result["compose"]["services"]) == {"minio", "milvus"}
    assert result["compose"]["services"]["milvus"]["mem_limit"] == "3g"
    milvus = result["compose"]["services"]["milvus"]
    assert any(
        (isinstance(v, dict) and v.get("target") == "/milvus/configs/user.yaml")
        or "milvus.yaml:/milvus/configs/user.yaml:ro" in str(v)
        for v in milvus["volumes"]
    )
    assert not any(str(x).startswith("/milvus/configs:") for x in milvus.get("tmpfs") or [])

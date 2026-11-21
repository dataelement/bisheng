"""F009 AC-08..25: render the real public Chart; fixtures are never releases."""

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "docker/helm/bisheng"
sys.path.insert(0, str(ROOT / "src/runtime-manager"))
from runtime_manager.deployment_policy import DeploymentPolicy  # noqa: E402 - repository test bootstrap.  # noqa: E402 - repository test bootstrap.  # noqa: E402 - repository test bootstrap.  # noqa: E402 - repository test bootstrap.  # noqa: E402 - repository test bootstrap.  # noqa: E402 - repository test bootstrap.

HELM = os.environ.get("HELM_BIN") or shutil.which("helm")


def merge(left, right):
    result = copy.deepcopy(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


@pytest.fixture(scope="session", autouse=True)
def dependencies():
    if not HELM:
        pytest.fail("HELM_BIN or helm on PATH is required")
    subprocess.run(
        [HELM, "dependency", "build", str(CHART), "--skip-refresh"],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def values():
    # Explicitly fictitious image refs, no build/push/cluster operations.
    return {
        "runtime": {
            "images": {
                name: "example.invalid/" + name + "@sha256:" + "a" * 64
                for name in (
                    "manager",
                    "entry",
                    "egress",
                    "admission",
                    "helper",
                    "assembler",
                )
            },
            "network": {
                "serviceCidrs": ["10.96.0.0/12"],
                "podCidrs": ["10.244.0.0/16"],
                "controlAllowedCidrs": ["10.244.0.0/16"],
                "entryAllowedCidrs": ["10.244.0.0/16"],
                "kubernetesApiCidrs": ["10.0.0.0/8"],
                "dnsCidrs": ["10.96.0.10/32"],
                "backendCidrs": ["10.96.0.0/12"],
            },
            "storage": {"sqliteCompatible": True},
        }
    }


def render(tmp_path, values, *, name="test", namespace="test", success=True):
    path = tmp_path / (name + "-values.yaml")
    path.write_text(yaml.safe_dump(values))
    result = subprocess.run(
        [HELM, "template", name, str(CHART), "--namespace", namespace, "-f", str(path)],
        text=True,
        capture_output=True,
    )
    if not success:
        assert result.returncode != 0
        return result.stderr
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def blueprint(documents):
    return next(
        json.loads(item["data"]["deployment.json"])
        for item in documents
        if item["kind"] == "ConfigMap" and "deployment.json" in item.get("data", {})
    )


def test_default_install_has_vibe_sandbox_and_no_gateway_or_environment_preflight(
    tmp_path, values
):
    documents = render(tmp_path, values)
    names = [item["metadata"]["name"] for item in documents]
    assert any("runtime-manager" in name for name in names)
    assert any("code-runner" in name for name in names)
    assert not any(item["kind"] == "CronJob" for item in documents)
    assert not any(
        item["kind"] == "Job"
        and (
            "verify" in item["metadata"]["name"]
            or "preflight" in item["metadata"]["name"]
        )
        for item in documents
    )
    assert not any("gateway" in name for name in names)
    assert not any(
        item["kind"] == "Namespace" and item["metadata"]["name"] == "test"
        for item in documents
    )
    settings = blueprint(documents)["settings"]
    assert settings["app_runtime"]["enabled"] is True
    assert settings["bs_client"]["enabled"] is True
    assert "platform_public_url" not in settings["bs_client"]
    assert "dsh" not in settings
    assert "admin" not in settings
    assert len(settings["sandbox_conf"]["endpoints"]) == 2
    for value in settings["sandbox_conf"]["endpoints"]:
        assert ".test.svc.cluster.local:" in value
    for item in documents:
        if item["kind"] == "Deployment" and item["metadata"]["name"].endswith(
            "-backend"
        ):
            assert (
                item["spec"]["template"]["spec"]["automountServiceAccountToken"]
                is False
            )


def test_policy_matches_real_rendered_quota_without_probe_report(tmp_path, values):
    documents = render(tmp_path, values)
    raw = next(
        item["data"]["descriptor.json"]
        for item in documents
        if item["kind"] == "ConfigMap" and "descriptor.json" in item.get("data", {})
    )
    policy = DeploymentPolicy.parse(raw)
    assert "probe_report" not in policy.document
    quota = next(item for item in documents if item["kind"] == "ResourceQuota")
    assert (
        quota["spec"]["hard"]["limits.cpu"]
        == f"{policy.document['cpu_budget_millicores']}m"
    )
    assert (
        quota["spec"]["hard"]["limits.memory"]
        == f"{policy.document['memory_budget_mb']}Mi"
    )
    assert blueprint(documents)["settings"]["app_runtime"][
        "runtime_kubernetes_nodes"
    ] == {policy.document["node_id"]: "/run/runtime-policy/descriptor.json"}
    backend = next(
        item
        for item in documents
        if item["kind"] == "Deployment"
        and item["metadata"]["name"].endswith("-backend")
    )
    descriptor_cm = next(
        item["metadata"]["name"]
        for item in documents
        if item["kind"] == "ConfigMap" and "descriptor.json" in item.get("data", {})
    )
    assert (
        next(
            item
            for item in backend["spec"]["template"]["spec"]["volumes"]
            if item["name"] == "runtime-policy"
        )["configMap"]["name"]
        == descriptor_cm
    )


def test_existing_secrets_and_external_components_do_not_create_instances(
    tmp_path, values
):
    overrides = {
        name: {"enabled": False, "external": {"host": name + ".company.example"}}
        for name in ("mysql", "redis", "minio", "elasticsearch", "milvus", "openfga")
    }
    overrides["database"] = {
        "host": "mysql.company.example",
        "auth": {"existingSecret": "company-platform-db"},
    }
    overrides["redis"]["auth"] = {"existingSecret": "company-redis"}
    overrides["minio"]["auth"] = {"existingSecret": "company-minio"}
    documents = render(tmp_path, merge(values, overrides))
    assert not any(
        item["kind"] == "StatefulSet"
        and not item["metadata"]["name"].endswith("code-runner")
        for item in documents
    )
    assert not any(
        item["kind"] == "Job" and "mysql-init" in item["metadata"]["name"]
        for item in documents
    )
    assert not any(
        item["kind"] == "Secret"
        and item["metadata"]["name"]
        in ("company-platform-db", "company-redis", "company-minio")
        for item in documents
    )
    assert blueprint(documents)["database"]["host"] == "mysql.company.example"


def test_mixed_dependencies_and_gateway_disabled_preserve_native_dsh(tmp_path, values):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "mysql": {"enabled": False},
                "database": {"host": "db.company.example"},
                "openfga": {"database": {"host": "db.company.example"}},
                "dsh": {"enabled": True},
                "publicUrl": "https://platform.example.com",
            },
        ),
    )
    assert blueprint(documents)["settings"]["bs_client"]["enabled"] is True
    assert any(
        item["kind"] == "Deployment" and item["metadata"]["name"].endswith("openfga")
        for item in documents
    )
    assert not any(
        item["kind"] == "StatefulSet" and item["metadata"]["name"].endswith("mysql")
        for item in documents
    )


def test_new_install_features_can_be_disabled_without_dangling_jobs(tmp_path, values):
    documents = render(
        tmp_path,
        merge(values, {"runtime": {"enabled": False}, "sandbox": {"enabled": False}}),
    )
    text = yaml.safe_dump_all(documents)
    assert "runtime_manager" not in text
    assert "code-runner" not in text
    assert "key-init" not in text
    assert blueprint(documents)["settings"]["app_runtime"]["enabled"] is False


def test_two_releases_and_namespaces_are_isolated_even_for_long_names(tmp_path, values):
    first = render(tmp_path, values, name="a" * 40 + "one")
    second = render(tmp_path, values, name="a" * 40 + "two")

    def identities(documents):
        return {(item["kind"], item["metadata"]["name"]) for item in documents}

    assert not identities(first) & identities(second)
    other = render(tmp_path, values, name="a" * 40 + "one", namespace="other")
    assert not identities(first) & identities(other)
    for item in first:
        if (
            item["kind"] == "NetworkPolicy"
            and item["metadata"].get("namespace", "test") == "test"
        ):
            assert item["spec"]["podSelector"]


@pytest.mark.parametrize(
    "storage_class,exists", [(None, False), ("", True), ("bounded-ext4", True)]
)
def test_cache_storage_class_three_states(tmp_path, values, storage_class, exists):
    documents = render(
        tmp_path,
        merge(
            values,
            {"backend": {"cache": {"enabled": True, "storageClass": storage_class}}},
        ),
    )
    claim = next(
        item
        for item in documents
        if item["kind"] == "PersistentVolumeClaim"
        and item["metadata"]["name"].endswith("backend-cache")
    )
    assert ("storageClassName" in claim["spec"]) is exists
    if exists:
        assert claim["spec"]["storageClassName"] == storage_class


def test_nondefault_resource_timeout_and_placement_propagate(tmp_path, values):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "backend": {
                    "resources": {"limits": {"memory": "1536Mi"}},
                    "nodeSelector": {"pool": "platform"},
                },
                "runtime": {
                    "execution": {
                        "helperResources": {
                            "image-check": {"memory_mb": 384, "cpu_millicores": 1250}
                        },
                        "timeouts": {"image_check": 240},
                        "placement": {"nodeSelector": {"pool": "apps"}},
                    }
                },
            },
        ),
    )
    raw = next(
        item["data"]["descriptor.json"]
        for item in documents
        if item["kind"] == "ConfigMap" and "descriptor.json" in item.get("data", {})
    )
    policy = DeploymentPolicy.parse(raw)
    assert policy.helper("image-check") == {"memory_mb": 384, "cpu_millicores": 1250}
    assert policy.timeout("image_check") == 240
    assert policy.document["placement"]["nodeSelector"]["pool"] == "apps"
    backend = next(
        item
        for item in documents
        if item["kind"] == "Deployment" and item["metadata"]["name"].endswith("backend")
    )
    assert backend["spec"]["template"]["spec"]["nodeSelector"]["pool"] == "platform"


@pytest.mark.parametrize(
    "override",
    [
        {"beat": {"replicaCount": 2}},
        {"database": {"engine": "unknown"}},
        {"backend": {"replicaCount": 2, "cache": {"enabled": True}}},
        {"config": {"existingConfigMap": "provided", "settings": {"dev": True}}},
        {"redis": {"cacheDb": 20}},
        {"runtime": {"network": {"serviceCidrs": []}}},
    ],
)
def test_unsafe_combinations_fail_before_install(tmp_path, values, override):
    assert render(tmp_path, merge(values, override), success=False)


def test_gateway_enabled_has_matching_initialization_and_license_binding(
    tmp_path, values
):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "gateway": {
                    "enabled": True,
                    "license": {"existingSecret": "customer-license"},
                }
            },
        ),
    )
    assert any(
        item["kind"] == "Job" and "gateway-init" in item["metadata"]["name"]
        for item in documents
    )
    config = next(
        item["data"]["application.yml"]
        for item in documents
        if item["kind"] == "ConfigMap" and "application.yml" in item.get("data", {})
    )
    parsed = yaml.safe_load(config)
    docker = yaml.safe_load(
        (ROOT / "docker/gateway/config/application.yml").read_text()
    )
    for application in (parsed, docker):
        gateway = application["spring"]["cloud"]["gateway"]
        routes = {route["id"]: route for route in gateway["routes"]}
        http, mobile = routes["bisheng-http"], routes["bisheng-dsh-mobile-ws"]
        assert len(http["predicates"]) == 1
        assert mobile["order"] < http.get("order", 0)
        assert mobile["uri"].startswith("ws://")
        assert mobile["predicates"] == [
            "Path=/api/v1/dsh/mobile/attach",
            "Header=Upgrade, (?i)websocket",
        ]
        assert not mobile.get("filters")
        assert gateway["global-filter"]["websocket-routing"]["enabled"] is False
        prefixes = application["bisheng"]["websocket"]["anonymous-path-prefixes"]
        assert "/api/v1/dsh/mobile/attach" in prefixes
        for path in ("/api/v1/dsh/mobile/bind", "/api/v1/dsh/mobile/desktops"):
            assert not any(
                path == prefix or path.startswith(prefix + "/") for prefix in prefixes
            )
        assert (
            application["logging"]["level"][
                "com.dataelem.gateway.filter.SelfWebsocketRoutingFilter"
            ]
            == "warn"
        )
    assert "customer-license" in yaml.safe_dump_all(documents)


def test_no_startup_monkeypatch_or_host_configuration(tmp_path, values):
    documents = render(tmp_path, values)
    for item in documents:
        if item["kind"] == "ConfigMap":
            assert not any(key.endswith(".py") for key in item.get("data", {}))
    text = yaml.safe_dump_all(documents)
    assert "192.168.106.122" not in text
    assert "node122" not in text
    assert "/root/k8s-product" not in text


def test_all_probe_named_ports_resolve_in_real_containers(tmp_path, values):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "gateway": {
                    "enabled": True,
                    "license": {"existingSecret": "test-license"},
                }
            },
        ),
    )
    for item in documents:
        if item["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        for container in item["spec"]["template"]["spec"]["containers"]:
            ports = {port.get("name") for port in container.get("ports", [])}
            for key in ("startupProbe", "readinessProbe", "livenessProbe"):
                probe = container.get(key, {})
                port = probe.get("httpGet", probe.get("tcpSocket", {})).get("port")
                if isinstance(port, str):
                    assert port in ports, (item["metadata"]["name"], key, port)


def test_manual_diagnostics_are_separate_and_internal_tls_has_destination_selector(
    tmp_path, values
):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "runtime": {"diagnostics": {"enabled": True}},
                "global": {"internalPlatformPort": 9443},
            },
        ),
    )
    diagnostic = next(
        row
        for row in documents
        if row["kind"] == "ConfigMap"
        and row["metadata"]["name"].endswith("runtime-diagnostics")
    )
    assert not diagnostic["data"]
    assert all(
        "probe_report" not in row.get("data", {}).get("descriptor.json", "")
        for row in documents
    )
    network = next(
        row
        for row in documents
        if row["kind"] == "NetworkPolicy"
        and row["metadata"]["name"].endswith("runtime-system-platform")
    )
    assert any(
        peer.get("podSelector", {})
        .get("matchLabels", {})
        .get("app.kubernetes.io/component")
        == "frontend"
        for rule in network["spec"]["egress"]
        if rule["ports"] == [{"protocol": "TCP", "port": 9443}]
        for peer in rule["to"]
    )
    key_job = next(
        row
        for row in documents
        if row["kind"] == "Job" and "key-init" in row["metadata"]["name"]
    )
    pod = key_job["spec"]["template"]["spec"]
    assert pod["securityContext"]["fsGroup"] == 10001
    assert pod["volumes"][0]["secret"]["defaultMode"] == 0o440


def test_mixed_external_schema_never_initialized_in_owned_mysql(tmp_path, values):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "database": {"host": "db.company.example"},
                "openfga": {"database": {"host": "fga.company.example"}},
            },
        ),
    )
    assert not any(
        row["kind"] == "Job" and "mysql-init" in row["metadata"]["name"]
        for row in documents
    )


@pytest.mark.parametrize("missing", [False, True])
def test_upgrade_preserves_all_crypto_roots_public_keys_and_tls(
    tmp_path, values, missing
):
    from tests.test_k8s_installation import chart_lookup_api

    namespace = "upgrade-test"
    initial = render(tmp_path, values, namespace=namespace)
    objects = {}
    for original in initial:
        if original["kind"] not in {"Secret", "ConfigMap"}:
            continue
        row = copy.deepcopy(original)
        meta = row["metadata"]
        meta.setdefault("namespace", namespace)
        meta.setdefault("annotations", {}).update(
            {
                "meta.helm.sh/release-name": "test",
                "meta.helm.sh/release-namespace": namespace,
            }
        )
        meta.setdefault("labels", {})["app.kubernetes.io/managed-by"] = "Helm"
        if meta["name"].endswith("data-public-keys"):
            row["data"] = {"public-keys.json": '{"data_v1":"' + "b" * 64 + '"}'}
        kind = "secrets" if row["kind"] == "Secret" else "configmaps"
        objects[f"/api/v1/namespaces/{meta['namespace']}/{kind}/{meta['name']}"] = row
    if missing:
        key = next(key for key in objects if key.endswith("-platform-keys"))
        objects.pop(key)
    path = tmp_path / "upgrade.yaml"
    path.write_text(yaml.safe_dump(values))
    with chart_lookup_api(objects) as (url, _):
        config = tmp_path / "kubeconfig.json"
        config.write_text(
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Config",
                    "clusters": [{"name": "fake", "cluster": {"server": url}}],
                    "users": [{"name": "fake", "user": {}}],
                    "contexts": [
                        {"name": "fake", "context": {"cluster": "fake", "user": "fake"}}
                    ],
                    "current-context": "fake",
                }
            )
        )
        result = subprocess.run(
            [
                HELM,
                "template",
                "test",
                str(CHART),
                "-n",
                namespace,
                "-f",
                str(path),
                "--is-upgrade",
                "--dry-run=server",
                "--kubeconfig",
                str(config),
            ],
            capture_output=True,
            text=True,
        )
    if missing:
        assert result.returncode != 0 and "restore the original" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    upgraded = [row for row in yaml.safe_load_all(result.stdout) if row]
    for row in upgraded:
        if row["kind"] == "Secret" or row["metadata"]["name"].endswith(
            "data-public-keys"
        ):
            kind = "secrets" if row["kind"] == "Secret" else "configmaps"
            key = f"/api/v1/namespaces/{row['metadata'].get('namespace', namespace)}/{kind}/{row['metadata']['name']}"
            assert row["data"] == objects[key]["data"]
    cert = next(
        row
        for row in upgraded
        if row["kind"] == "Secret" and row["metadata"]["name"].endswith("internal-tls")
    )
    webhook = next(
        row for row in upgraded if row["kind"] == "ValidatingWebhookConfiguration"
    )
    assert all(
        hook["clientConfig"]["caBundle"] == cert["data"]["ca.crt"]
        for hook in webhook["webhooks"]
    )


def test_global_secret_references_reach_children_without_render_order_dependency(
    tmp_path, values
):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "global": {
                    "credentials": {
                        "existingRuntimeSecret": "operator-runtime",
                        "existingIssuerSecret": "operator-issuer",
                        "existingDataSecret": "operator-data",
                    }
                }
            },
        ),
    )
    assert not any(
        row["kind"] == "Secret"
        and row["metadata"]["name"]
        in {"operator-runtime", "operator-issuer", "operator-data"}
        for row in documents
    )
    manager = next(
        row
        for row in documents
        if row["kind"] == "Deployment"
        and row["metadata"]["name"].endswith("runtime-manager")
    )
    pod = manager["spec"]["template"]["spec"]
    refs = [
        env["valueFrom"]["secretKeyRef"]["name"]
        for env in pod["containers"][0]["env"]
        if "valueFrom" in env
    ]
    assert refs and set(refs) == {"operator-runtime"}
    issuer = next(
        volume for volume in pod["volumes"] if volume["name"] == "material-issuer"
    )
    assert issuer["secret"]["secretName"] == "operator-issuer"
    job = next(
        row
        for row in documents
        if row["kind"] == "Job" and "key-init" in row["metadata"]["name"]
    )
    assert (
        job["spec"]["template"]["spec"]["volumes"][0]["secret"]["secretName"]
        == "operator-data"
    )


def test_nodeport_backend_port_and_database_volume_permissions_are_parameters(
    tmp_path, values
):
    documents = render(
        tmp_path,
        merge(
            values,
            {
                "frontend": {
                    "service": {
                        "type": "NodePort",
                        "nodePort": 30080,
                        "clientNodePort": 30081,
                    }
                },
                "backend": {"service": {"port": 8765}},
            },
        ),
    )
    front = next(
        row
        for row in documents
        if row["kind"] == "Service" and row["metadata"]["name"].endswith("frontend")
    )
    assert [port["nodePort"] for port in front["spec"]["ports"]] == [30080, 30081]
    backend = next(
        row
        for row in documents
        if row["kind"] == "Deployment" and row["metadata"]["name"].endswith("backend")
    )
    env = backend["spec"]["template"]["spec"]["containers"][0]["env"]
    assert (
        next(item["value"] for item in env if item["name"] == "BISHENG_API_PORT")
        == "8765"
    )
    es = next(
        row
        for row in documents
        if row["kind"] == "StatefulSet"
        and row["metadata"]["name"].endswith("elasticsearch")
    )
    assert es["spec"]["template"]["spec"]["securityContext"]["fsGroup"] == 1001


def test_config_and_policy_updates_trigger_rollouts_without_startup_patches(
    tmp_path, values
):
    first = render(tmp_path, values)
    changed = render(
        tmp_path,
        merge(
            values,
            {
                "config": {"settings": {"database_pool": {"pool_size": 20}}},
                "runtime": {"execution": {"timeouts": {"health": 180}}},
                "gateway": {"enabled": True, "license": {"existingSecret": "license"}},
            },
        ),
    )

    def annotations(documents, suffix):
        return next(
            row["spec"]["template"]["metadata"]["annotations"]
            for row in documents
            if row["kind"] == "Deployment" and row["metadata"]["name"].endswith(suffix)
        )

    assert (
        annotations(first, "-backend")["checksum/settings"]
        != annotations(changed, "-backend")["checksum/settings"]
    )
    assert (
        annotations(first, "-backend")["checksum/runtime-policy"]
        != annotations(changed, "-backend")["checksum/runtime-policy"]
    )
    assert (
        annotations(first, "-runtime-manager")["checksum/deployment-policy"]
        != annotations(changed, "-runtime-manager")["checksum/deployment-policy"]
    )
    assert (
        annotations(first, "-frontend")["checksum/nginx"]
        != annotations(changed, "-frontend")["checksum/nginx"]
    )
    external = render(
        tmp_path,
        merge(
            values,
            {
                "config": {"existingConfigMap": "company-settings"},
                "global": {"configRevision": "rotation-2"},
            },
        ),
    )
    for suffix in ("-backend", "-runtime-manager", "-frontend"):
        assert (
            annotations(external, suffix)["deployment.bisheng.io/config-revision"]
            == "rotation-2"
        )


def test_partial_external_tls_is_rejected_before_claiming_external_ca(tmp_path, values):
    error = render(
        tmp_path,
        merge(
            values, {"global": {"credentials": {"existingCaConfigMap": "company-ca"}}}
        ),
        success=False,
    )
    assert "external TLS" in error


@pytest.mark.parametrize(
    "overrides,enabled",
    [
        ({"dsh": {"enabled": False}}, False),
        ({"dsh": {"enabled": False}, "bs_client": {}}, True),
        ({"bs_client": {"enabled": False}}, False),
        ({"config": {"settings": {"dsh": {"enabled": False}}}}, False),
        ({"config": {"settings": {"bs_client": {}, "dsh": {"enabled": False}}}}, True),
    ],
)
def test_client_defaults_and_legacy_overrides(tmp_path, values, overrides, enabled):
    """覆盖 AC: AC-01, AC-06, AC-08."""
    settings = blueprint(render(tmp_path, merge(values, overrides)))["settings"]
    assert settings["bs_client"].get("enabled", True) is enabled
    assert "dsh" not in settings


def test_client_proxy_records_resolve_pods_not_service_cluster_ip(tmp_path, values):
    documents = render(tmp_path, values)
    settings = blueprint(documents)["settings"]
    peer_service = next(
        row
        for row in documents
        if row["kind"] == "Service"
        and row["metadata"]["name"].endswith("frontend-peers")
    )
    assert peer_service["spec"]["clusterIP"] == "None"
    assert peer_service["spec"]["selector"]["app.kubernetes.io/component"] == "frontend"
    assert settings["bs_client"]["trusted_proxy_hosts"][0].startswith(
        peer_service["metadata"]["name"] + "."
    )


def test_compose_default_package_sources_reach_wheels_and_npm_only_during_build():
    """覆盖 AC: AC-02, AC-03, AC-09 — deployment values drive the real policy."""
    from runtime_manager.config import Config
    from runtime_manager.egress import build_destinations, decide, runtime_destinations

    variables = dict(
        line.split("=", 1)
        for line in (ROOT / "docker/.env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    config = Config(
        build_index_url=variables["BISHENG_RTM_BUILD_INDEX_URL"],
        build_npm_registry=variables["BISHENG_RTM_BUILD_NPM_REGISTRY"],
    )
    for host in ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]:
        assert decide(build_destinations(config), host, 443).allowed
        assert not decide(
            runtime_destinations(config, platform_api_base="https://platform.example"),
            host,
            443,
        ).allowed
    private = config.with_overrides(
        build_index_url="https://python.company.example/simple",
        build_npm_registry="https://npm.company.example",
    )
    for host in ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]:
        assert not decide(build_destinations(private), host, 443).allowed


def test_edge_proxy_does_not_forward_arbitrary_client_scheme(tmp_path, values):
    """覆盖 AC: AC-07 — the trusted backend peer must also sanitize its edge."""
    documents = render(tmp_path, values)
    nginx = next(
        row["data"]["default.conf"]
        for row in documents
        if row["kind"] == "ConfigMap" and "default.conf" in row.get("data", {})
    )
    assert "geo $bs_trusted_edge" in nginx
    assert 'default $scheme; "1:http" http; "1:https" https;' in nginx
    assert "map $http_host $bs_forwarded_host" in nginx
    assert "default $http_x_forwarded_proto" not in nginx

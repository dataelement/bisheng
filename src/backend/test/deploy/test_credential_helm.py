"""Credential keyring contract of the standard Helm chart (v3.1.0-beta2 on the beta1 chart).

Every backend-image process — render-settings, wait-initialization, the
initialization Job and each long-running Deployment — must receive the same
external keyring through BS_SECRET_KEYS_FILE; there is no built-in key.
Source contracts always run; real rendering runs when Helm is installed.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "docker/helm/bisheng"
TEMPLATES = CHART / "templates"
KEYRING_FILE = "/run/settings-secrets/credential-keys/keys.json"
UPGRADE_MESSAGE = "credential keyring Secret is missing on upgrade"


def _define(name: str) -> str:
    text = (TEMPLATES / "_helpers.tpl").read_text()
    match = re.search(
        r'{{-? define "' + re.escape(name) + r'" -?}}(.*?){{-? end -?}}\n(?={{-? define|\Z|\n)', text, re.S
    )
    assert match, name
    return match.group(1)


def test_keyring_is_projected_and_exported_to_every_backend_container():
    volumes = _define("bisheng.secretVolumes")
    assert 'name: {{ include "bisheng.keyringSecret" . }}' in volumes
    assert "items: [{key: keys.json, path: credential-keys/keys.json}]" in volumes
    assert _define("bisheng.keyringFile").strip() == KEYRING_FILE
    assert 'BS_SECRET_KEYS_FILE, value: {{ include "bisheng.keyringFile" . }}' in _define("bisheng.backendEnv")
    # render-settings encrypts with the keyring, so it needs the variable too.
    assert 'BS_SECRET_KEYS_FILE, value: {{ include "bisheng.keyringFile" . }}' in _define("bisheng.renderInit")

    deployment = (TEMPLATES / "_deployment.tpl").read_text()
    assert 'include "bisheng.renderInit" $root' in deployment
    # wait-initialization and the main container both use backendEnv/backendMounts.
    assert deployment.count('include "bisheng.backendEnv" $root') == 2
    assert deployment.count('include "bisheng.backendMounts" $root') == 2
    initialization = (TEMPLATES / "initialization.yaml").read_text()
    assert 'include "bisheng.renderInit" .' in initialization
    assert 'include "bisheng.backendEnv" .' in initialization
    for name in ("backend", "worker", "linsight", "beat"):
        assert (
            f'include "bisheng.backendDeployment" (list . "{name}")'
            in (TEMPLATES / f"{name}-deployment.yaml").read_text()
        )


def test_keyring_secret_generation_and_upgrade_guard_are_declared():
    secret = (TEMPLATES / "secret.yaml").read_text()
    assert 'include "bisheng.credentialEnvGuard" .' in secret
    assert '(list . "credential-keys")' in secret
    assert '"keys.json" (dict "version" 1 "keys" (list $fernet)' in secret
    assert UPGRADE_MESSAGE in secret and "existingKeyringSecret" in secret
    # Fernet keys are URL-safe base64; Sprig randBytes is standard base64.
    assert 'randBytes 32 | replace "+" "-" | replace "/" "_"' in secret
    assert '(hasSuffix "-credential-keys" $name)' in _define("bisheng.ownedSecret")


def test_values_expose_only_the_keyring_reference_and_no_legacy_credential_shapes():
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert values["global"]["credentials"]["existingKeyringSecret"] == ""
    assert "middleware" not in values and "credentials" not in values
    schema = json.loads((CHART / "values.schema.json").read_text())
    credentials = schema["properties"]["global"]["properties"]["credentials"]
    assert credentials["additionalProperties"] is False
    assert credentials["properties"]["existingKeyringSecret"] == {"type": "string"}
    guard = _define("bisheng.credentialEnvGuard")
    for name in ("config", "BS_SECRET_KEYS_FILE", "bisheng_DATABASE_URL"):
        assert f'"{name}"' in guard
    for component in ("backend", "worker", "linsight", "beat"):
        assert f'"{component}"' in guard
    assert ".Values.config.extraEnv" in guard


# --------------------------------------------------------------------- real Helm

HELM = shutil.which("helm")
RUNTIME_OFF = {"runtime": {"enabled": False}}


@pytest.fixture(scope="module")
def helm():
    if not HELM:
        pytest.skip("Helm executable unavailable: real rendering NOT EXECUTED")
    build = subprocess.run([HELM, "dependency", "build", str(CHART), "--skip-refresh"], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    return HELM


def _render(helm, tmp_path, values, *extra):
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    return subprocess.run(
        [helm, "template", "security", str(CHART), "-n", "bisheng", "-f", str(path), *extra],
        capture_output=True,
        text=True,
    )


def _backend_pods(documents):
    for row in documents:
        if row["kind"] == "Deployment" and row["metadata"]["name"].endswith(("backend", "worker", "linsight", "beat")):
            yield row["spec"]["template"]["spec"]
        elif row["kind"] == "Job" and any(
            c["name"] == "render-settings" for c in row["spec"]["template"]["spec"].get("initContainers", [])
        ):
            yield row["spec"]["template"]["spec"]


def test_rendered_backend_containers_share_one_projected_keyring(helm, tmp_path):
    result = _render(helm, tmp_path, RUNTIME_OFF)
    assert result.returncode == 0, result.stderr
    documents = [row for row in yaml.safe_load_all(result.stdout) if row]
    keyring = next(
        row for row in documents if row["kind"] == "Secret" and row["metadata"]["name"].endswith("-credential-keys")
    )
    import base64

    document = json.loads(base64.b64decode(keyring["data"]["keys.json"]))
    assert document["version"] == 1 and len(document["keys"]) == 1
    from cryptography.fernet import Fernet

    Fernet(document["keys"][0].encode())  # valid URL-safe 32-byte key
    pods = list(_backend_pods(documents))
    assert len(pods) >= 5  # backend, worker, linsight, beat and the initialization Job
    for pod in pods:
        containers = pod.get("initContainers", []) + pod["containers"]
        backend_image = [c for c in containers if "bisheng-backend" in c["image"]]
        assert "render-settings" in {c["name"] for c in backend_image}
        for container in backend_image:
            env = {item["name"]: item.get("value") for item in container.get("env", [])}
            assert env.get("BS_SECRET_KEYS_FILE") == KEYRING_FILE, container["name"]
        projected = next(v for v in pod["volumes"] if v["name"] == "settings-secrets")["projected"]["sources"]
        assert any(
            source["secret"]["name"] == keyring["metadata"]["name"]
            and source["secret"]["items"] == [{"key": "keys.json", "path": "credential-keys/keys.json"}]
            for source in projected
        )


def test_existing_keyring_secret_replaces_the_generated_one(helm, tmp_path):
    values = {**RUNTIME_OFF, "global": {"credentials": {"existingKeyringSecret": "operator-keys"}}}
    result = _render(helm, tmp_path, values)
    assert result.returncode == 0, result.stderr
    documents = [row for row in yaml.safe_load_all(result.stdout) if row]
    assert not any(
        row["kind"] == "Secret" and row["metadata"]["name"].endswith("-credential-keys") for row in documents
    )
    for pod in _backend_pods(documents):
        projected = next(v for v in pod["volumes"] if v["name"] == "settings-secrets")["projected"]["sources"]
        assert any(source["secret"]["name"] == "operator-keys" for source in projected)


@pytest.mark.parametrize("name", ["BS_SECRET_KEYS_FILE", "config", "bisheng_DATABASE_URL"])
def test_extra_env_cannot_override_credential_sources(helm, tmp_path, name):
    values = {**RUNTIME_OFF, "worker": {"extraEnv": [{"name": name, "value": "do-not-display"}]}}
    result = _render(helm, tmp_path, values)
    assert result.returncode != 0
    assert "extraEnv must not override" in result.stderr and "do-not-display" not in result.stderr


def test_upgrade_without_keyring_refuses_silent_key_generation(helm, tmp_path):
    result = _render(helm, tmp_path, RUNTIME_OFF, "--is-upgrade")
    assert result.returncode != 0
    assert UPGRADE_MESSAGE in result.stderr

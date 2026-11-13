"""Render real Helm when installed; also guard declarative source contracts."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "docker/helm/bisheng"


def test_chart_uses_external_secret_for_all_python_processes():
    for name in ("backend", "worker", "linsight"):
        text = (CHART / f"templates/{name}-deployment.yaml").read_text()
        assert "bisheng.credentialRevision" in text
        assert "bisheng.credentialMounts" in text
        assert "bisheng.credentialVolume" in text
        assert "configMap:" not in text
    text = (CHART / "templates/secret.yaml").read_text()
    assert "minioSecretKey:" not in text and "sandboxToken:" in text
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert values["credentials"]["existingSecret"] == ""
    assert "middleware" not in values


def test_helm_render_and_reject_legacy_values():
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("Helm executable unavailable: real rendering NOT EXECUTED")
    args = [
        helm,
        "template",
        "security",
        str(CHART),
        "--set",
        "credentials.existingSecret=credential-a",
        "--set",
        "credentials.configRevision=revision-a",
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    docs = list(yaml.safe_load_all(result.stdout))
    deployments = [
        d
        for d in docs
        if d and d["kind"] == "Deployment" and d["metadata"]["name"].endswith(("backend", "worker", "linsight"))
    ]
    assert len(deployments) == 3
    for d in deployments:
        pod = d["spec"]["template"]
        assert pod["metadata"]["annotations"]["bisheng.io/credential-revision"] == "revision-a"
        assert pod["spec"]["volumes"][0]["secret"]["secretName"] == "credential-a"
    bad = subprocess.run([*args, "--set", "middleware.minio.secretKey=do-not-display"], capture_output=True, text=True)
    assert bad.returncode != 0 and "do-not-display" not in bad.stderr
    assert "migrate" in bad.stderr

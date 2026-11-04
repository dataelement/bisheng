"""Source-level checks for the sandbox image and compose wiring (F068 T025 / T026).

Image build and CapDrop inspect still need docker; these assertions catch the
contracts that can be verified without pulling an image.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from serve import build_app

_REPO = Path(__file__).resolve().parents[4]
_DOCKERFILE = _REPO / "docker" / "bisheng-sandbox" / "Dockerfile"
_COMPOSE = _REPO / "docker" / "docker-compose.yml"
_HELM_VALUES = _REPO / "docker" / "helm" / "bisheng-sandbox" / "values.yaml"
_RUNNER_CAPS = {"SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE", "KILL"}
_COPY_IN_TOTAL_DEFAULT = "536870912"


def test_serve_requires_non_empty_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBOX_TOKEN", "")
    monkeypatch.setenv("SANDBOX_SESSIONS_ROOT", str(tmp_path / "sessions"))
    with pytest.raises(RuntimeError, match="token"):
        build_app()


def test_serve_builds_app_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBOX_TOKEN", "compose-token")
    monkeypatch.setenv("SANDBOX_SESSIONS_ROOT", str(tmp_path / "sessions"))
    app = build_app()
    assert app.state.token == "compose-token"


def test_dockerfile_is_single_multiarch_image_without_platform_payload():
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in text
    assert "libreoffice-impress" in text
    assert "libreoffice-calc" in text
    assert "fonts-wqy-zenhei" in text
    assert "pandoc-3.6.4" in text
    assert "ffmpeg" in text
    assert "uv sync --frozen --no-dev --no-install-project" in text
    assert "COPY src/sandbox-runner" in text or "COPY --chmod=0555 src/sandbox-runner" in text
    assert "USER 65534" in text
    assert "serve.py" in text
    assert "pip install --no-cache-dir uv" in text
    assert "mirrors.tuna.tsinghua.edu.cn" in text
    assert "astral.sh" not in text
    assert "--mount=type=cache,target=/var/lib/apt" not in text
    assert "playwright install" not in text
    copies = [line for line in text.splitlines() if line.strip().startswith("COPY ")]
    joined = "\n".join(copies)
    assert "config.yaml" not in joined
    assert "entrypoint.sh" not in joined
    assert "bisheng/" not in joined


def test_compose_named_runners_and_hardening():
    data = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    assert data["networks"]["sandbox_net"]["internal"] is False
    worker = data["services"]["backend_worker"]
    assert "sandbox_net" in worker["networks"]
    assert "default" in worker["networks"]
    assert worker["volumes"][0].endswith(":ro")
    assert worker["volumes"][1].endswith(":ro")
    assert "config.yaml" in worker["volumes"][0]
    assert "entrypoint.sh" in worker["volumes"][1]
    backend = data["services"]["backend"]
    assert backend["volumes"][0].endswith(":ro")
    assert backend["volumes"][1].endswith(":ro")
    assert "sandbox_net" in backend["networks"]
    assert "default" in backend["networks"]
    assert "BS_SANDBOX_CONF__TOKEN" in backend["environment"]
    expected_endpoints = '["http://code-runner-1:8080","http://code-runner-2:8080"]'
    assert backend["environment"]["BS_SANDBOX_CONF__ENDPOINTS"] == expected_endpoints
    assert worker["environment"]["BS_SANDBOX_CONF__ENDPOINTS"] == expected_endpoints
    assert "DISCOVER" not in " ".join(backend["environment"])
    assert "DISCOVER" not in " ".join(worker["environment"])

    for name in ("code-runner-1", "code-runner-2"):
        svc = data["services"][name]
        assert svc["networks"] == ["sandbox_net"]
        assert "ports" not in svc
        assert "deploy" not in svc
        assert svc["user"] == "0"
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert set(svc.get("cap_add") or []) == _RUNNER_CAPS
        # The image's tini is PID 1; compose's init would push it to PID 2.
        assert "init" not in svc
        assert str(svc["cpus"]) == "${SANDBOX_CPUS:-2}"
        assert "no-new-privileges:true" in svc["security_opt"]
        mem = str(svc["mem_limit"]).lower()
        assert mem.endswith("g")
        assert float(mem[:-1]) >= 2
        assert int(svc["pids_limit"]) >= 1
        assert any(str(item).startswith("/tmp") for item in svc["tmpfs"])
        env = svc["environment"]
        joined = " ".join(f"{k}={v}" for k, v in env.items()) if isinstance(env, dict) else " ".join(env)
        env_map = env if isinstance(env, dict) else {}
        assert str(env_map.get("SANDBOX_MAX_SESSIONS")) == "50"
        assert str(env_map.get("SANDBOX_MAX_COPY_IN_TOTAL_BYTES")) == _COPY_IN_TOTAL_DEFAULT
        assert str(env_map.get("SANDBOX_ENABLE_UID_ISOLATION")).lower() == "true"
        assert "minio" not in joined.lower()
        assert "mysql" not in joined.lower()
        assert "hmac" not in joined.lower()
        assert "SANDBOX_TOKEN" in (env if isinstance(env, dict) else joined)
        depends = svc.get("depends_on") or {}
        assert "mysql" not in depends
        assert "redis" not in depends


def test_dockerfile_tini_pid1_passwd_and_matplotlibrc():
    text = _DOCKERFILE.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    # tini installed and wrapping the unchanged runner command.
    assert "tini \\" in lines
    assert 'ENTRYPOINT ["tini", "--"]' in lines
    assert lines.index('ENTRYPOINT ["tini", "--"]') < lines.index('CMD ["python", "serve.py"]')
    # passwd / group entries for every session uid, written at build time.
    assert "$(seq 10000 10999)" in text
    assert "sandbox${uid}:x:${uid}:${uid}:" in text and ">> /etc/passwd" in text
    assert "sandbox${uid}:x:${uid}:" in text and ">> /etc/group" in text
    # CJK font first in matplotlib's sans-serif list.
    assert "'font.sans-serif: WenQuanYi Zen Hei, DejaVu Sans'" in text
    assert "> /etc/matplotlibrc" in text
    assert "ENV MATPLOTLIBRC=/etc/matplotlibrc" in lines
    # Build-time steps run as root, before the runtime user is set.
    user_at = lines.index("USER 65534")
    assert lines.index("ENV MATPLOTLIBRC=/etc/matplotlibrc") < user_at
    assert next(i for i, line in enumerate(lines) if "$(seq 10000 10999)" in line) < user_at


def test_helm_values_match_compose_hardening():
    values = yaml.safe_load(_HELM_VALUES.read_text(encoding="utf-8"))
    caps = values["securityContext"]["capabilities"]
    assert caps["drop"] == ["ALL"]
    assert set(caps["add"]) == _RUNNER_CAPS
    assert values["securityContext"]["readOnlyRootFilesystem"] is True
    limits = values["resources"]["limits"]
    assert str(limits["cpu"]) == "2"
    assert str(limits["memory"]) == "2Gi"
    assert values["env"]["SANDBOX_MAX_COPY_IN_TOTAL_BYTES"] == _COPY_IN_TOTAL_DEFAULT
    assert values["env"]["SANDBOX_MAX_SESSIONS"] == "50"


def test_compose_sessions_root_is_disk_backed_per_replica():
    """Session dirs and the copy-in spool must not sit on tmpfs (charged to mem_limit)."""
    data = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    host_dirs = set()
    for name in ("code-runner-1", "code-runner-2"):
        svc = data["services"][name]
        root = svc["environment"]["SANDBOX_SESSIONS_ROOT"]
        assert root == "/sessions"
        # Not under any tmpfs mount.
        tmpfs_paths = [str(item).split(":", 1)[0] for item in svc["tmpfs"]]
        assert not any(root == p or root.startswith(p.rstrip("/") + "/") for p in tmpfs_paths)
        mounts = [v for v in svc["volumes"] if str(v).endswith(":" + root)]
        assert len(mounts) == 1
        host_dirs.add(mounts[0].rsplit(":", 1)[0])
        # Orphan session dirs from a previous run are cleared, then the runner execs.
        cmd = svc["command"]
        assert cmd[:2] == ["sh", "-c"]
        assert f"find {root} -mindepth 1 -delete" in cmd[2]
        assert cmd[2].rstrip().endswith("exec python serve.py")
    # Each replica wipes its own directory at start; sharing one would wipe the other's sessions.
    assert len(host_dirs) == 2


def test_env_example_documents_sandbox_cpus():
    text = (_REPO / "docker" / ".env.example").read_text(encoding="utf-8")
    assert "SANDBOX_CPUS" in text


def test_gateway_startup_includes_object_storage_ready_for_api_and_worker():
    services = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]
    pending = ["gateway"]
    reachable = set()
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(services[name].get("depends_on") or [])

    assert "minio" in reachable
    assert services["minio"]["healthcheck"]["test"]
    for name in ("backend", "backend_worker"):
        assert services[name]["depends_on"]["minio"]["condition"] == "service_healthy"

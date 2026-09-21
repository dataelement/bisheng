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
    assert data["networks"]["sandbox_net"]["internal"] is True
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
    assert "sandbox_net" not in (backend.get("networks") or ["default"])

    for name in ("code-runner-1", "code-runner-2"):
        svc = data["services"][name]
        assert svc["networks"] == ["sandbox_net"]
        assert "ports" not in svc
        assert "deploy" not in svc
        assert svc["user"] == "0"
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert set(svc.get("cap_add") or []) == {"SETUID", "SETGID", "CHOWN"}
        assert "no-new-privileges:true" in svc["security_opt"]
        mem = str(svc["mem_limit"]).lower()
        assert mem.endswith("g")
        assert float(mem[:-1]) >= 2
        assert int(svc["pids_limit"]) >= 1
        assert any(str(item).startswith("/tmp") for item in svc["tmpfs"])
        env = svc["environment"]
        joined = " ".join(f"{k}={v}" for k, v in env.items()) if isinstance(env, dict) else " ".join(env)
        env_map = env if isinstance(env, dict) else {}
        assert str(env_map.get("SANDBOX_MAX_SESSIONS")) == "2"
        assert str(env_map.get("SANDBOX_ENABLE_UID_ISOLATION")).lower() == "true"
        assert "minio" not in joined.lower()
        assert "mysql" not in joined.lower()
        assert "hmac" not in joined.lower()
        assert "SANDBOX_TOKEN" in (env if isinstance(env, dict) else joined)
        depends = svc.get("depends_on") or {}
        assert "mysql" not in depends
        assert "redis" not in depends

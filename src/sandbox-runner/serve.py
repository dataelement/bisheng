"""PID 1 for the isolation-environment runner. Must not import bisheng."""

from __future__ import annotations

import os

import uvicorn
from app import create_app


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_app():
    token = (os.environ.get("SANDBOX_TOKEN") or "").strip()
    return create_app(
        token=token,
        sessions_root=os.environ.get("SANDBOX_SESSIONS_ROOT") or "/tmp/sessions",
        max_sessions=int(os.environ.get("SANDBOX_MAX_SESSIONS") or "1"),
        lease_ttl_s=float(os.environ.get("SANDBOX_LEASE_TTL_S") or "900"),
        max_copy_in_bytes=int(os.environ.get("SANDBOX_MAX_COPY_IN_BYTES") or str(50 * 1024 * 1024)),
        enable_uid_isolation=_bool_env("SANDBOX_ENABLE_UID_ISOLATION", False),
    )


def main() -> None:
    app = build_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("SANDBOX_PORT") or "8080"),
        workers=1,
    )


if __name__ == "__main__":
    main()

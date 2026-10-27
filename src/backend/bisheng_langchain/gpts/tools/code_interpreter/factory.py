"""Build a local, container, or e2b code executor.

Callers keep their own result shape. This module only selects the backend.
"""

from bisheng.common.services.config_service import load_sandbox_conf
from bisheng_langchain.gpts.tools.code_interpreter.base_executor import BaseExecutor
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

# Isolation-environment access knobs live on Settings.sandbox_conf, never extra.
# Runner-only keys and retired hostname-scan keys are stripped so leftover tool
# config cannot override the pool.
_CONTAINER_POOL_KEYS = (
    "endpoints",
    "token",
    "discover_host_pattern",
    "discover_index_start",
    "discover_max",
    "discover_ttl_s",
    "discover_port",
    "pool_lease_ttl_s",
    "max_sessions_per_replica",
    "enable_uid_isolation",
    "pool_acquire_timeout_s",
    "max_copy_in_bytes",
    "sandbox_conf",
)

_KINDS = ("local", "container", "e2b")


def build_code_executor(kind: str, **kwargs) -> BaseExecutor:
    """kind: local | container | e2b. Unknown kinds raise and do not fall through."""
    if kind not in _KINDS:
        raise ValueError(f"Unknown code interpreter type: {kind!r}")
    config = kwargs.pop("config", None) or {}
    backend = config.get(kind) if isinstance(config, dict) else None
    if isinstance(backend, dict):
        kwargs.update(backend)
    # Frontend stores config.e2b.type as private/official. Domain empty vs
    # non-empty is the real private vs official switch.
    kwargs.pop("type", None)
    if kind == "container":
        for key in _CONTAINER_POOL_KEYS:
            kwargs.pop(key, None)
        kwargs["sandbox_conf"] = load_sandbox_conf()
        return ContainerExecutor(**kwargs)
    if kind == "e2b":
        return E2bCodeExecutor(**kwargs)
    return LocalExecutor(**kwargs)


def refresh_open_code_executors(tools) -> None:
    """Point open container executors at the current page config, in place.

    Sticky sessions (keep_session) and local / e2b executors are left alone.
    A live lease is released through ``_release`` before the address changes.
    """
    if not tools:
        return
    pending = []
    for tool in tools:
        if getattr(tool, "name", None) != "bisheng_code_interpreter":
            continue
        executor = getattr(tool, "executor", None)
        if not isinstance(executor, ContainerExecutor):
            continue
        if getattr(executor, "keep_session", False):
            continue
        pending.append(executor)
    if not pending:
        return
    conf = load_sandbox_conf()
    endpoints = [str(url).rstrip("/") for url in (conf.endpoints or [])]
    token = conf.token or ""
    seen: set[int] = set()
    for executor in pending:
        identity = id(executor)
        if identity in seen:
            continue
        seen.add(identity)
        if executor._bound_url and executor._session_id:
            executor._release()
        executor.endpoints = list(endpoints)
        executor.token = token

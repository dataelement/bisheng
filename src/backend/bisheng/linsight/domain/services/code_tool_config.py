"""Bind the code interpreter's executor config to a workspace directory.

Shared by task mode and F078 (workflow agent nodes, assistants). The function
only rewrites the config dict; looking up the tool row and building the tool
stays with each caller.
"""

from __future__ import annotations

import os

from e2b.sandbox.filesystem.filesystem import WriteEntry
from loguru import logger

from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import SIZE_AUTOPUSH


def build_e2b_file_list(file_dir: str) -> list[WriteEntry]:
    """Files the E2B sandbox receives when the code tool is constructed.

    The walk happens at tool init, so skill bundles have to already be in
    ``file_dir``. A file over ``SIZE_AUTOPUSH`` (5 MiB) is left out; the local
    and container executors still read it from the session directory.
    """
    file_list: list[WriteEntry] = []
    oversized: list[str] = []
    for root, _dirs, files in os.walk(file_dir):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                if os.path.getsize(file_path) > SIZE_AUTOPUSH:
                    oversized.append(file_path)
                    continue
            except OSError:
                # Unstattable file: let it through; the push surfaces real problems.
                pass
            file_list.append(WriteEntry(data=file_path, path=file_path.replace(file_dir, ".")))
    if oversized:
        # Never let a bounded copy-in look complete: the model is told these
        # paths exist, so a silent drop reads as "the tool is broken".
        logger.warning(
            "code interpreter: {} file(s) exceed the E2B auto-push ceiling ({} bytes) and were not "
            "pushed into the sandbox: {}",
            len(oversized),
            SIZE_AUTOPUSH,
            ", ".join(os.path.basename(p) for p in oversized),
        )
    return file_list


def bind_code_config_to_workspace(code_config: dict, file_dir: str, workspace_prefix: str | None) -> dict:
    """Point the configured executor at ``file_dir`` and mirror writes to ``workspace_prefix``.

    ``code_config`` is the tool's preset extra (``{"type": ..., "config": {...}}``)
    and is modified in place. Only the executor named by ``type`` is configured;
    an unknown type raises ``SandboxConfigurationError``. The E2B copy-in list is
    built from ``file_dir`` as it is NOW, so call this only after the workspace
    has been fully prepared.
    """
    from bisheng.common.errcode.sandbox import SandboxConfigurationError

    executor_type = code_config.get("type") or "local"
    if executor_type not in {"local", "container", "e2b"}:
        raise SandboxConfigurationError()
    # Normalize the default before the factory selects config[executor_type].
    code_config["type"] = executor_type
    executor_config = code_config.setdefault("config", {}).setdefault(executor_type, {})
    executor_config["local_sync_path"] = file_dir
    if workspace_prefix:
        # File tools and follow-up runs read the same durable workspace.
        executor_config["workspace_prefix"] = workspace_prefix
    if executor_type == "local":
        # Keep one run dir for the whole run; the caller releases it
        # (release_local_run) before deleting file_dir.
        executor_config["keep_run_dir"] = True
    elif executor_type == "container":
        # Sticky replica + work dir across tool calls of one run.
        executor_config["keep_session"] = True
        executor_config["timeout"] = 3600
    elif executor_type == "e2b":
        executor_config["timeout"] = 3600
        executor_config["keep_sandbox"] = True
        # E2B eagerly reads this copy-in set. Local uses the task directory
        # directly; container copies its working set at run().
        executor_config["file_list"] = build_e2b_file_list(file_dir)
    return code_config

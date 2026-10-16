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


def bind_code_config_to_workspace(code_config: dict, file_dir: str, workspace_prefix: str | None) -> dict:
    """Point every executor kind at ``file_dir`` and mirror writes to ``workspace_prefix``.

    ``code_config`` is the tool's preset extra (``{"type": ..., "config": {...}}``)
    and is modified in place. The E2B copy-in list is built from ``file_dir`` as it
    is NOW, so call this only after the workspace has been fully prepared.
    """
    executor_type = code_config.get("type") or "local"
    config = code_config.setdefault("config", {})

    local = config.setdefault("local", {})
    local["local_sync_path"] = file_dir
    # With local isolation on, keep one run dir for the whole run; the caller
    # releases it (release_local_run) before deleting file_dir.
    local["keep_run_dir"] = True

    container = config.setdefault("container", {})
    container["local_sync_path"] = file_dir
    # Sticky replica + work dir across tool calls of one run.
    container["keep_session"] = True
    container["timeout"] = 3600

    if workspace_prefix:
        # Lets the executor mirror what it writes into the MinIO workspace, so the
        # file tools and the next run can see code-generated files.
        local["workspace_prefix"] = workspace_prefix
        container["workspace_prefix"] = workspace_prefix

    e2b = config.setdefault("e2b", {})
    e2b["local_sync_path"] = file_dir
    e2b["timeout"] = 3600
    e2b["keep_sandbox"] = True
    # ``file_list`` is the E2B copy-in set, capped by E2B at SIZE_AUTOPUSH. The
    # container executor copies in at run time, so it needs no pre-scan.
    if executor_type != "container":
        file_list = []
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
        e2b["file_list"] = file_list
    return code_config

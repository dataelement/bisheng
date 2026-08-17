"""Credential storage: `~/.bisheng/credentials.json`, 0600, multi-profile.

The key is stored **in clear text** and that is not an oversight — every request
has to send the original value, so there is nothing to derive it from. The file
mode is therefore the entire protection, which has one direct consequence for
the code below: the file is created with `os.open(..., 0o600)` in a single step.
"Write it, then chmod it" leaves a window in which the file is world-readable,
and on a shared jump host that window is the whole attack.

`scopes` are never persisted. The server re-evaluates them per call; a cached
copy can only produce the "the admin ticked the box but the CLI still says no"
failure, which is unfalsifiable from the user's side.

The multi-profile shape ships this round even though `--platform` does not.
Writing the single-platform shape (key at the top level) would turn adding a
second platform into a migration; the profile layer costs ten lines now and zero
later.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bisheng_cli.errors import EXIT_NOT_LOGGED_IN, CliError

STORE_VERSION = 1
DIR_NAME = ".bisheng"
FILE_NAME = "credentials.json"

# The snapshot is for display only (design D3). Adding a field here means adding
# something the CLI will show the user without re-checking it against the server.
SNAPSHOT_FIELDS = (
    "base_url",
    "api_key",
    "key_mask",
    "tenant_id",
    "service_account",
    "resource_owner",
    "expires_at",
    "logged_in_at",
)


@dataclass
class Profile:
    base_url: str
    api_key: str
    key_mask: str | None = None
    tenant_id: int | None = None
    service_account: dict[str, Any] | None = None
    resource_owner: dict[str, Any] | None = None
    expires_at: str | None = None
    logged_in_at: str | None = None


def normalise_base_url(raw: str) -> str:
    """Canonical spelling of a platform address — the ONE implementation.

    Both the credential profile key and `.bisheng/app.json`'s per-platform key go
    through this function. Two implementations would drift, and the drift shows
    up as "login succeeded but the next command says you are not logged in", or
    worse, an iterative deploy that reads no saved app_id and creates a second
    draft application on the platform.

    Trailing slash and case are normalised. An explicitly written `:80` / `:443`
    is **kept**: dropping it would be a guess about the operator's nginx setup,
    and a wrong guess there merges two genuinely different platforms.
    """
    text = (raw or "").strip()
    if not text:
        raise CliError("平台地址为空", exit_code=EXIT_NOT_LOGGED_IN, next_step="请执行 bisheng login <平台地址>。")
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def credentials_path() -> Path:
    return Path.home() / DIR_NAME / FILE_NAME


def _is_windows() -> bool:
    return os.name == "nt"


def _run_icacls(path: Path) -> bool:
    """Restrict `path` to the current user. Returns False if that failed."""
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if not user:
        return False
    try:
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _harden(path: Path, warn: Callable[[str], None] | None) -> None:
    if not _is_windows():
        return
    if _run_icacls(path):
        return
    if warn is not None:
        warn(
            f"无法收紧 {path} 的访问权限：本机其它账号可能读到明文密钥。"
            "请手动执行 icacls 限制该文件，或改用专用账号运行 CLI。"
        )


def _read_store() -> dict[str, Any]:
    path = credentials_path()
    if not path.exists():
        return {"version": STORE_VERSION, "current": None, "profiles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        # Never silently reset: the file holds the only copy of a key the admin
        # handed over once, and overwriting it turns a typo into a re-issue.
        raise CliError(
            f"凭据文件无法解析：{exc}",
            exit_code=EXIT_NOT_LOGGED_IN,
            next_step=f"检查或删除 {path} 后重新执行 bisheng login。",
        )
    if not isinstance(data, dict) or "profiles" not in data:
        raise CliError(
            "凭据文件结构无法识别",
            exit_code=EXIT_NOT_LOGGED_IN,
            next_step=f"检查或删除 {path} 后重新执行 bisheng login。",
        )
    return data


def _write_store(store: dict[str, Any], warn: Callable[[str], None] | None) -> None:
    path = credentials_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _is_windows():
        os.chmod(path.parent, 0o700)
    payload = json.dumps(store, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    # O_CREAT|O_EXCL with the mode argument — the file is never world-readable,
    # not even for the instant between open() and chmod().
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    _harden(path, warn)


def save_profile(base_url: str, profile: dict[str, Any], *, warn: Callable[[str], None] | None = None) -> None:
    """Write one platform's profile and make it current."""
    key = normalise_base_url(base_url)
    stored = {field: profile.get(field) for field in SNAPSHOT_FIELDS}
    stored["base_url"] = key
    stored["logged_in_at"] = profile.get("logged_in_at") or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    store = _read_store()
    store["version"] = STORE_VERSION
    store.setdefault("profiles", {})[key] = stored
    store["current"] = key
    _write_store(store, warn)


def load_profile(base_url: str) -> Profile:
    key = normalise_base_url(base_url)
    store = _read_store()
    raw = store.get("profiles", {}).get(key)
    if not raw:
        raise CliError(
            f"本机没有 {key} 的凭据",
            exit_code=EXIT_NOT_LOGGED_IN,
            next_step=f"先执行 bisheng login {key}。",
        )
    return _to_profile(raw)


def load_current() -> Profile:
    store = _read_store()
    current = store.get("current")
    raw = store.get("profiles", {}).get(current) if current else None
    if not raw:
        raise CliError(
            "尚未登录任何平台",
            exit_code=EXIT_NOT_LOGGED_IN,
            next_step="先执行 bisheng login <平台地址>。",
        )
    return _to_profile(raw)


def _to_profile(raw: dict[str, Any]) -> Profile:
    return Profile(**{field: raw.get(field) for field in SNAPSHOT_FIELDS})

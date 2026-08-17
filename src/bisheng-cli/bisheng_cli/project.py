"""Project layer: locate the root, fast-fail on the manifest, remember the app id.

Two boundaries this module refuses to cross.

**It does not validate the manifest.** `bisheng-app.yaml` is owned by F055 and its
model is `extra='forbid'`. Checking "exists / parses / has name, runtime, port"
catches the failure that is worth catching locally (a wasted upload) without
creating a second, drifting copy of the schema. Adding a default value here is
how "it passed locally but the platform rejected it" gets manufactured.

**It does not write the manifest.** The app identity lives beside it in
`.bisheng/app.json` instead — a file the CLI owns end to end, which is committed
to git (so a team shares one app) yet structurally excluded from the upload
package (so it never reaches the platform). Those two facts are independent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml

from bisheng_cli.credentials import normalise_base_url
from bisheng_cli.errors import EXIT_LOCAL_INVALID, EXIT_USAGE, CliError

MANIFEST_NAME = "bisheng-app.yaml"
STATE_DIR = ".bisheng"
APP_REF_NAME = "app.json"
APP_REF_VERSION = 1
REQUIRED_FIELDS = ("name", "runtime", "port")

# Re-exported so callers (and the test that asserts identity) reach the single
# implementation rather than a second one that happens to agree today.
__all__ = [
    "MANIFEST_NAME",
    "REQUIRED_FIELDS",
    "find_project_root",
    "load_manifest",
    "normalise_base_url",
    "read_app_ref",
    "require_app_id",
    "resolve_app_id",
    "save_app_ref",
]


def find_project_root(path: str | Path) -> Path:
    root = Path(path).expanduser()
    if not root.exists():
        raise CliError(
            f"路径不存在：{root}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="检查 deploy 的 PATH 参数。",
        )
    if not root.is_dir():
        raise CliError(
            f"项目根必须是目录：{root}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="把 PATH 指向项目根目录，而不是其中的某个文件。",
        )
    return root.resolve()


def load_manifest(root: Path) -> dict[str, Any]:
    """Existence + parseability + three required fields. Nothing else."""
    path = Path(root) / MANIFEST_NAME
    if not path.is_file():
        raise CliError(
            f"项目根缺少 {MANIFEST_NAME}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step=f"在 {root} 下创建 {MANIFEST_NAME}，至少写明 name / runtime / port。",
        )
    try:
        # safe_load only. full_load / unsafe_load honour `!!python/object`, which
        # makes reading a manifest equivalent to running it.
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CliError(
            f"{MANIFEST_NAME} 无法解析：{exc}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="按 YAML 语法修正该文件后重试；错误信息里的 line / column 指向出错位置。",
        )
    if not isinstance(data, dict):
        raise CliError(
            f"{MANIFEST_NAME} 的顶层必须是键值映射",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="参考「部署纳管」文档的最小示例重写该文件。",
        )
    missing = [field for field in REQUIRED_FIELDS if data.get(field) is None]
    if missing:
        raise CliError(
            f"{MANIFEST_NAME} 缺少必填项：{', '.join(missing)}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step=f"补齐 {', '.join(missing)} 后重试；其余字段的合法性由平台托管预检判定。",
        )
    return data


# ---- .bisheng/app.json --------------------------------------------------


def _app_ref_path(root: Path) -> Path:
    return Path(root) / STATE_DIR / APP_REF_NAME


def _read_store(root: Path) -> dict[str, Any]:
    path = _app_ref_path(root)
    if not path.is_file():
        return {"version": APP_REF_VERSION, "apps": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CliError(
            f"{path} 无法解析：{exc}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step=f"删除 {path} 后用 --app-id 显式指定目标应用重发。",
        )
    if not isinstance(data, dict) or "apps" not in data:
        return {"version": APP_REF_VERSION, "apps": {}}
    return data


def save_app_ref(
    root: Path,
    base_url: str,
    *,
    app_id: str,
    app_name: str | None = None,
    slug: str | None = None,
    last_deployment_id: str | None = None,
) -> None:
    key = normalise_base_url(base_url)
    store = _read_store(root)
    entry = store.setdefault("apps", {}).get(key, {})
    entry.update(
        {
            "app_id": app_id,
            "app_name": app_name if app_name is not None else entry.get("app_name"),
            "slug": slug if slug is not None else entry.get("slug"),
            "last_deployment_id": (
                last_deployment_id if last_deployment_id is not None else entry.get("last_deployment_id")
            ),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    )
    store["version"] = APP_REF_VERSION
    store["apps"][key] = entry
    path = _app_ref_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_app_ref(root: Path, base_url: str) -> dict[str, Any] | None:
    return _read_store(root).get("apps", {}).get(normalise_base_url(base_url))


def resolve_app_id(root: Path, base_url: str, explicit: str | None) -> str | None:
    """Explicit flag wins; otherwise the saved id; otherwise None (first deploy)."""
    if explicit:
        return explicit
    entry = read_app_ref(root, base_url)
    return entry.get("app_id") if entry else None


def require_app_id(root: Path, base_url: str, explicit: str | None) -> str:
    """Same, but for commands that cannot invent a target (e.g. `logs`)."""
    app_id = resolve_app_id(root, base_url, explicit)
    if app_id:
        return app_id
    raise CliError(
        "无法确定目标应用",
        exit_code=EXIT_USAGE,
        next_step=f"用 --app-id 显式指定，或在曾经 deploy 过的项目目录下执行（标识存放在 {STATE_DIR}/{APP_REF_NAME}）。",
    )

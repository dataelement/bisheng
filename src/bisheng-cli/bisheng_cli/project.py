"""Project layer: locate the root, fast-fail on the manifest, remember the app id.

Two boundaries this module refuses to cross.

**It does not validate the manifest.** `bisheng-app.yaml` is owned by F055 and its
model is `extra='forbid'`. Checking "exists / parses / has name, runtime, port"
catches the failure that is worth catching locally (a wasted upload) without
creating a second, drifting copy of the schema. Adding a default value here is
how "it passed locally but the platform rejected it" gets manufactured.

**It never rewrites an existing manifest.** The explicit init command only
creates a new bundle scaffold; validation remains platform-owned. The app identity lives beside it in
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


def initialize_project(path: Path, runtime: str = "python3.11") -> dict[str, Any]:
    """Create a new scaffold atomically with respect to pre-existing file names."""
    root = Path(path).expanduser().resolve()
    if runtime not in {"python3.11", "node20", "static"}:
        raise CliError("Unsupported scaffold runtime", exit_code=EXIT_LOCAL_INVALID)
    manifest = {"manifest_version": 2, "name": root.name or "application", "runtime": runtime, "port": 8080}
    if runtime == "python3.11":
        command = ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
        files = {
            "main.py": 'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/")\ndef home():\n    return {"status": "ok"}\n',
            "requirements.txt": "fastapi\nuvicorn\nbisheng-sdk==0.1.1\n",
        }
    elif runtime == "node20":
        command = ["node", "server.js"]
        package = {"name": "bisheng-app", "version": "1.0.0", "private": True, "scripts": {"start": "node server.js"}}
        lock = {
            "name": "bisheng-app",
            "version": "1.0.0",
            "lockfileVersion": 3,
            "packages": {"": {"name": "bisheng-app", "version": "1.0.0"}},
        }
        files = {
            "package.json": json.dumps(package, indent=2) + "\n",
            "package-lock.json": json.dumps(lock, indent=2) + "\n",
            "server.js": 'require("http").createServer((req,res)=>{res.end("Application ready");}).listen(Number(process.env.PORT||8080),"0.0.0.0");\n',
        }
    else:
        command = ["nginx", "-g", "daemon off;"]
        files = {
            "index.html": '<!doctype html><html><head><meta charset="utf-8"><title>Application</title></head><body>Application ready</body></html>\n'
        }
    manifest["delivery"] = {"mode": "bundle", "startup": {"command": command}}
    files[MANIFEST_NAME] = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    conflicts = [name for name in files if (root / name).exists()]
    if conflicts:
        raise CliError("Project files already exist: " + ", ".join(conflicts), exit_code=EXIT_LOCAL_INVALID)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        with (root / name).open("x", encoding="utf-8") as output:
            output.write(content)
    return {"path": str(root), "runtime": runtime, "manifest_version": 2, "delivery_mode": "bundle"}


def run_init(args, emitter) -> int:
    result = initialize_project(Path(args.path), args.runtime)
    emitter.info("Created application bundle project: " + result["path"])
    emitter.result("init", ok=True, exit_code=0, data=result)
    return 0

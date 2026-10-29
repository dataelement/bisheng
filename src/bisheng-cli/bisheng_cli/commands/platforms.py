"""`bisheng platforms list` / `bisheng platforms use <BASE_URL>` — the multi-platform
interaction layer (T047, AC-12).

The data shape has been multi-profile since T012; this command only reads and
re-points it. Two rules:

* **The key never leaves the store through this command.** `list` prints the
  mask the platform handed back at login (`key_mask`), never the value — a
  listing is exactly the kind of output that gets pasted into a chat.
* **`use` cannot invent a profile.** Switching to an address that was never
  logged into is refused with exit 3 and the address in the message, because
  the fix is `bisheng login <that address>`, not editing the store.

`--platform` (the per-invocation form of the same choice) lives in `cli.py` and
is resolved by `credentials.load_selected`; both forms read the same store.
"""

from __future__ import annotations

from typing import Any

from bisheng_cli import credentials
from bisheng_cli.errors import EXIT_OK, EXIT_USAGE
from bisheng_cli.output import Emitter

COMMAND = "platforms"


def run(args: Any, emitter: Emitter) -> int:
    sub = getattr(args, "platforms_command", None)
    if sub == "list":
        return _list(emitter)
    if sub == "use":
        return _use(args, emitter)
    emitter.error("用法: bisheng platforms list | bisheng platforms use <BASE_URL>")
    emitter.error("列出本机已登录的平台，或把其中一个设为后续命令的默认平台。")
    return EXIT_USAGE


def _list(emitter: Emitter) -> int:
    rows = credentials.list_profiles()
    if not rows:
        emitter.info("本机尚未登录任何平台。先执行 bisheng login <平台地址>。")
    for row in rows:
        marker = "*" if row["current"] else " "
        who = row.get("actor_name") or "(未命名)"
        kind = "个人访问令牌" if row.get("actor_kind") == "natural_person" else "服务账号"
        expires = row.get("expires_at") or "未设置"
        emitter.info(
            f"{marker} {row['base_url']}  {kind}: {who}  密钥: {row.get('key_mask') or '(无掩码)'}  到期: {expires}"
        )
    if rows:
        emitter.info("（* = 当前默认平台；换默认用 bisheng platforms use <BASE_URL>，单次指定用 --platform）")
    emitter.result(COMMAND, ok=True, exit_code=EXIT_OK, data={"platforms": rows})
    return EXIT_OK


def _use(args: Any, emitter: Emitter) -> int:
    key = credentials.set_current(args.base_url, warn=emitter.warn)
    emitter.info(f"默认平台已切换为 {key}")
    emitter.result(COMMAND, ok=True, exit_code=EXIT_OK, data={"current": key})
    return EXIT_OK

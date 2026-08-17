"""`bisheng logs` — show the caller their own app's runtime logs.

**The CLI makes no ownership decision.** owner-only is enforced server-side
against the key's *resource owner* (not its subject), and the CLI cannot see that
field at all. Pre-checking here would add a second judge working from worse data;
it would eventually disagree with the first, and the disagreement would look like
a permission bug. So the request goes out, and 16205 / 16254 come back as
sentences.

**`--follow` is polling, not a stream.** The whole chain — v2 endpoint → F054's
v1 endpoint → runtime-manager → `docker logs` — is one-shot responses, and nginx
caps a held connection at 300s anyway. Polling brings its own hazard: docker
timestamps have one-second resolution, so the last second's lines come back again
on the next `since` window. Hence the content-hash de-duplication; without it a
followed log looks like an app screaming the same line.

**Empty is not the same as "never happened".** Nothing came back either because
there is no running instance, or because the window predates the log rotation
budget. The CLI says which of the two it cannot distinguish rather than printing
a blank.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from bisheng_cli import credentials, project
from bisheng_cli.errors import EXIT_OK
from bisheng_cli.http import PlatformClient
from bisheng_cli.output import Emitter

COMMAND = "logs"
LOGS_PATH = "/api/v2/apps/{app_id}/logs"

# Short polling only; see the module docstring for why a stream is not an option.
FOLLOW_INTERVAL = 3.0
# How many trailing lines to remember for de-duplication. Larger than any single
# second's realistic output, small enough to stay free.
DEDUPE_WINDOW = 500


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now_epoch() -> int:
    return int(time.time())


def _digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest()


def run(args: Any, emitter: Emitter) -> int:
    profile = credentials.load_current()
    base_url = profile.base_url
    root = project.find_project_root(".")
    app_id = project.require_app_id(root, base_url, args.app_id)
    path = LOGS_PATH.format(app_id=app_id)

    client = PlatformClient(
        base_url,
        api_key=profile.api_key,
        trust_env=not getattr(args, "no_proxy", False),
        timeout=getattr(args, "timeout", None),
        emitter=emitter,
    )

    printed = 0
    last_lines: list[str] = []
    seen: set[str] = set()
    # The user's `--since` is forwarded verbatim: the server accepts epoch
    # seconds or a `30m` / `2h` / `7d` window, and converting one form into the
    # other locally would be a second implementation of the same semantics.
    since: Any = args.since
    interrupted = False

    try:
        with client:
            while True:
                requested_at = _now_epoch()
                params: dict[str, Any] = {"tail": args.tail}
                if since is not None:
                    params["since"] = since
                if args.keyword:
                    # Filtered inside runtime-manager, so fewer than `tail` lines
                    # can come back. That is the design, not a short read — the
                    # CLI must not retry or warn about it.
                    params["keyword"] = args.keyword

                data = client.get_json(path, params=params) or {}
                lines = [str(line) for line in (data.get("lines") or [])]
                fresh = [line for line in lines if _digest(line) not in seen]
                for line in fresh:
                    emitter.info(line)
                printed += len(fresh)
                last_lines = lines
                seen = {_digest(line) for line in lines[-DEDUPE_WINDOW:]}

                if not args.follow:
                    break
                since = requested_at
                _sleep(FOLLOW_INTERVAL)
    except KeyboardInterrupt:
        interrupted = True
        emitter.info("已停止跟踪。")

    if not last_lines and not interrupted:
        _explain_empty(emitter, args)

    data_out: dict[str, Any] = {"app_id": app_id, "line_count": printed}
    if not args.follow:
        data_out["lines"] = last_lines
    emitter.result(COMMAND, ok=True, exit_code=EXIT_OK, data=data_out)
    return EXIT_OK


def _explain_empty(emitter: Emitter, args: Any) -> None:
    if args.since:
        emitter.info("该时间段没有日志，或日志已被轮转（平台对保留期不做承诺）——这不代表这段时间什么都没发生。")
        return
    # Degraded until F055 adds `app_state` / `pending_reason` to the logs payload
    # (write-back 2): the CLI cannot name the state, but naming the candidates
    # still beats printing nothing at all.
    emitter.info("未取到日志：应用可能没有运行实例（草稿 / 待上线 / 已停运），请在应用详情页确认应用态。")

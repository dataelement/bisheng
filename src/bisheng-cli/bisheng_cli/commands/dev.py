"""`bisheng dev` — run the app locally, wired the way the platform would wire it.

The command orchestrates three pieces and owns none of their logic:
`devdb` (the project-local SQLite plus the same-named environment), `devproxy`
(the mini proxy that injects identity per request) and the app process itself,
started by the same resolution order as the hosted entrypoint. What this file
decides is the **order of the pre-checks** (T044) and **what the developer is
told** (AC-24):

1. credentials — no profile is exit 3 with zero requests (AC-51 / AC-29);
2. the manifest — missing file or a missing `name` / `runtime` / `port` is
   exit 6 naming the field, before anything is started (AC-53);
3. the platform — `probe` (exit 7 / 8 / 9 / 2) then `whoami` (exit 4 on a
   revoked key). **No scope is checked** (AC-29, same as `login`): a key with
   no permission bit ticked yet can still run the app locally; what it can
   *do* against the platform is the platform's call, per call.

Only then does anything happen on this machine: the database is prepared, the
app process is spawned with the injected environment, the proxy comes up in
front of it, and the identity source is printed — service account name, the
platform it came from, the local URL — so nobody mistakes the injected subject
for a real visitor (AC-24). Ctrl-C tears both down.

What the developer does not get: `--as` or any identity override (AC-25), and
a proxy for platform-capability calls (决议-3 — the app calls the platform
directly with the same environment it will have hosted).
"""

from __future__ import annotations

import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from bisheng_cli import credentials, devdb, project
from bisheng_cli.devproxy import DevIdentity, DevProxy, HandleMinter
from bisheng_cli.errors import EXIT_LOCAL_INVALID, EXIT_OK, EXIT_USAGE, CliError
from bisheng_cli.http import PlatformClient, probe
from bisheng_cli.output import Emitter

COMMAND = "dev"
WHOAMI_PATH = "/api/v2/auth/whoami"

#: How long to give the app after SIGTERM before SIGKILL on shutdown.
_STOP_GRACE_SECONDS = 5.0


def run(args: Any, emitter: Emitter) -> int:
    profile = credentials.load_selected(args)
    root = project.find_project_root(args.path)
    manifest = project.load_manifest(root)

    client = PlatformClient(
        profile.base_url,
        api_key=profile.api_key,
        trust_env=not getattr(args, "no_proxy", False),
        timeout=getattr(args, "timeout", None),
        emitter=emitter,
    )
    with client:
        probe(client)
        whoami = client.get_json(WHOAMI_PATH) or {}

    app_ref = project.read_app_ref(root, profile.base_url)
    app_id = (app_ref or {}).get("app_id")
    identity = DevIdentity.from_whoami(whoami, app_id=app_id)

    proxy_port = int(args.port) if getattr(args, "port", None) else int(manifest["port"])
    app_port = int(args.app_port) if getattr(args, "app_port", None) else devdb.pick_free_port(exclude=proxy_port)
    if app_port == proxy_port:
        raise CliError(
            f"本地访问入口与应用进程不能用同一个端口（{proxy_port}）",
            exit_code=EXIT_USAGE,
            next_step="去掉 --app-port 让 CLI 自动挑一个，或给两者不同的端口。",
        )

    db = devdb.prepare_dev_db(root)
    env = devdb.build_dev_env(
        manifest=manifest,
        app_port=app_port,
        platform_base_url=profile.base_url,
        app_id=app_id,
        db=db,
    )
    start = devdb.resolve_start_command(root)

    proxy = DevProxy(
        identity=identity,
        minter=HandleMinter(identity),
        app_port=app_port,
        listen_port=proxy_port,
        emitter=emitter,
    )
    process = spawn_app(start, root, env)
    try:
        proxy.start()
    except OSError as exc:
        _terminate(process)
        raise CliError(
            f"本地访问入口无法监听 127.0.0.1:{proxy_port}：{exc.strerror or exc.__class__.__name__}",
            exit_code=EXIT_USAGE,
            next_step="用 --port 换一个未被占用的端口。",
        )

    _report(emitter, profile, whoami, identity, proxy.url, app_port, db, start)
    # A long-running command: the machine-readable "it is up, here is where" is
    # a `stage` event, so that `result` (with the real exit code) stays the
    # last line on stdout when the session ends.
    emitter.stage(
        COMMAND,
        "ready",
        "running",
        data={
            "base_url": profile.base_url,
            "actor_kind": whoami.get("actor_kind"),
            "actor_id": whoami.get("actor_id"),
            "actor_name": whoami.get("actor_name"),
            "subject_kind": identity.subject_kind,
            "app_id": app_id,
            "local_url": proxy.url,
            "app_port": app_port,
            "db_path": str(db.path),
            "start_command": start.display,
            "start_source": start.source,
        },
    )
    try:
        return run_session(process, proxy, emitter)
    finally:
        proxy.stop()
        _terminate(process)


# ---- process handling (module-level so tests can replace them) ---------------


def spawn_app(start: devdb.StartCommand, root: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    """Start the app in the project root; its stdout/stderr stay on the terminal."""
    try:
        return subprocess.Popen(start.argv, cwd=str(root), env=env)
    except OSError as exc:
        raise CliError(
            f"启动应用失败（{start.display}）：{exc.strerror or exc.__class__.__name__}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="确认启动命令可执行；改用 BISHENG_APP_START 或 Procfile 的 web: 行显式指定。",
        )


def run_session(process: subprocess.Popen[bytes], proxy: DevProxy, emitter: Emitter) -> int:
    """Block until Ctrl-C or the app exits on its own.

    An app that exits by itself is reported with its code: a non-zero exit is
    almost always the app failing to bind `PORT` or crashing at import, and
    that is exit 6 here — the same class of "fix the project" failure the
    hosted probe would report as 16228.
    """
    try:
        while True:
            code = process.poll()
            if code is not None:
                if code == 0:
                    emitter.info("应用进程已退出。")
                    return EXIT_OK
                emitter.error(f"应用进程异常退出（code {code}）。托管环境里这会是启动探活失败（16228）。")
                return EXIT_LOCAL_INVALID
            time.sleep(0.2)
    except KeyboardInterrupt:
        emitter.info("收到 Ctrl-C，正在停止应用与本地入口……")
        return EXIT_OK


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    except (OSError, ValueError):
        # Already gone, or the handle is closed; nothing to stop.
        return


# ---- output --------------------------------------------------------------------


def _report(
    emitter: Emitter,
    profile: credentials.Profile,
    whoami: dict[str, Any],
    identity: DevIdentity,
    local_url: str,
    app_port: int,
    db: devdb.DevDatabase,
    start: devdb.StartCommand,
) -> None:
    """AC-24: identity source and account, platform, local URL — no key, ever."""
    who = whoami.get("actor_name") or "(未命名)"
    if whoami.get("actor_kind") == "natural_person":
        emitter.info(f"注入身份: {who}（个人访问令牌持有人，来自 {profile.base_url} 的 login 凭据）")
    else:
        emitter.info(f"注入身份: 服务账号 {who}（来自 {profile.base_url} 的 login 凭据）")
    emitter.info(
        f"  应用看到的访问者恒为这个账号（X-BiSheng-Subject-Kind={identity.subject_kind}）；"
        "线上看到的是真实访问用户，本地无法模拟他人身份。"
    )
    emitter.info(f"本地访问地址: {local_url}")
    emitter.info(
        f"  应用进程监听 127.0.0.1:{app_port}（PORT / BISHENG_APP_PORT），启动命令来自 {start.source}：{start.display}"
    )
    emitter.info(f"  应用数据库: {db.path}（BISHENG_APP_DB_URL / BISHENG_APP_DB_PATH，跨重启保留，不进上传包）")
    emitter.info("  BISHENG_APP_BASE_PATH 为空串；平台上是 /apps/<slug>，对外链接请经它拼接。")
    emitter.info("Ctrl-C 停止。")

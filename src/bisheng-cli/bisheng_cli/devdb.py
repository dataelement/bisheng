"""`bisheng dev`'s local database and the environment it hands the app (T043).

Everything the hosted runtime injects, the local run injects under the **same
name** — that is the whole contract (F054 `contracts-runtime-manager.md` §5,
INV-32), and the list below is a mirror of `runtime_manager.lifecycle.build_env`
rather than a second definition: `tests/test_platform_contract.py` reads that
function with `ast` and fails if the two sets of names ever differ. What
differs is only the *values*: the database is a SQLite file inside the project,
the base path is empty, the version is `dev`.

Where the database lives and why (AC-26): `<project>/.bisheng/dev/app.db`.
Inside the project so a `git clone` + `bisheng dev` on another machine starts
from the same place; under `.bisheng/` because that directory is a **hard**
packaging exclude (`ignore.py`) — the file can never ride into an upload, and
`!` in `.bishengignore` cannot bring it back. It is never deleted by the CLI,
so data survives restarts.

Two things deliberately kept out of the child environment (AC-27):

* the login key under its own name — `BISHENG_API_KEY` is stripped even if the
  developer's shell exports it. The one place the credential does reach the app
  is `OPENAI_API_KEY` (see below), which is the platform's name for "the
  credential this process calls the model face with" and is what the hosted
  runtime fills with the application's own token;
* any per-request visitor credential — that arrives per request in a header
  (`devproxy`), never as a process-level variable.

**The model face's three names** (`contracts-runtime-manager.md` §5, F051
design D2): `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `BISHENG_MODEL_BASE_URL`.
Hosted, `OPENAI_API_KEY` carries the application's runtime credential
(`BISHENG_APP_TOKEN`'s value); under `dev` it carries the developer's own
service-account key, so the same `OpenAI(...)` line works in both places and
the call is judged against exactly the scopes that key was granted (AC-28).
The base URL is **read from `whoami.model_base_url`**, never composed here:
F051 AC-30 makes that field the single outward spelling of the address.

These three are platform-owned names like the rest, so they override the shell —
and when the platform answers with no model face (the open-capability layer is
not deployed), they are *removed* rather than inherited. Leaving a developer's
personal `OPENAI_API_KEY` in place would point the app at api.openai.com and
make it work locally in a way it can never work hosted.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bisheng_cli.errors import EXIT_LOCAL_INVALID, CliError
from bisheng_cli.project import STATE_DIR

DEV_SUBDIR = "dev"
DB_FILE_NAME = "app.db"

#: Same tuple as `runtime_manager.lifecycle.RESERVED_ENV_PREFIXES`: names the
#: platform owns and the app cannot redefine.
RESERVED_ENV_PREFIXES: tuple[str, ...] = ("BISHENG_APP_", "BISHENG_PLATFORM_", "PORT")

#: The contract list — `contracts-runtime-manager.md` §5, as `build_env` sets it.
PLATFORM_ENV_NAMES: tuple[str, ...] = (
    "BISHENG_APP_DB_URL",
    "BISHENG_APP_DB_PATH",
    "BISHENG_APP_ID",
    "BISHENG_APP_SLUG",
    "BISHENG_APP_VERSION",
    "BISHENG_APP_VERSION_ID",
    "BISHENG_PLATFORM_API_BASE",
    "PORT",
    "BISHENG_APP_PORT",
    "BISHENG_APP_BASE_PATH",
    "BISHENG_APP_HEALTH_PATH",
)

#: The model protocol face's names, declared in the same contract section as
#: `PLATFORM_ENV_NAMES` but set by a different producer hosted (F055 T056 fills
#: them from the app's runtime credential, not by `lifecycle.build_env`), which
#: is why they are a separate tuple here rather than three more entries above.
#: `tests/test_platform_contract.py` reads the contract document itself so this
#: list cannot drift away from it.
MODEL_FACE_ENV_NAMES: tuple[str, ...] = (
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "BISHENG_MODEL_BASE_URL",
)

#: Framework spellings of the base path, exported by the hosted image's
#: `entrypoint.sh.j2` from `BISHENG_APP_BASE_PATH`. Set here too, and set
#: unconditionally (empty is the correct value at the root path), so the app
#: behaves identically in both places.
FRAMEWORK_ENV_NAMES: tuple[str, ...] = (
    "UVICORN_ROOT_PATH",
    "STREAMLIT_SERVER_BASE_URL_PATH",
    "GRADIO_ROOT_PATH",
    "FORWARDED_ALLOW_IPS",
)

#: Never reaches the child process, whatever the shell exports.
LOGIN_KEY_ENV = "BISHENG_API_KEY"

DEFAULT_HEALTH_PATH = "/"
DEV_VERSION = "dev"


@dataclass(frozen=True)
class DevDatabase:
    path: Path
    url: str


def dev_state_dir(root: Path) -> Path:
    return Path(root) / STATE_DIR / DEV_SUBDIR


def prepare_dev_db(root: Path) -> DevDatabase:
    """Create (or reuse) the project-local SQLite file and return its two spellings.

    The file is created here rather than left to the app's first connect, so a
    read-only-at-start app finds a database and so the path printed at start-up
    is a path that exists. Re-runs are no-ops: existing data is untouched.
    """
    path = dev_state_dir(root) / DB_FILE_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(path).close()
    except (OSError, sqlite3.Error) as exc:
        raise CliError(
            f"无法在项目里创建本地应用数据库 {path}：{exc.__class__.__name__}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="确认项目目录可写；若 .bisheng/dev/ 被占用或损坏，删除后重试。",
        )
    # `sqlite:///` + an absolute POSIX path yields the four-slash form the hosted
    # runtime uses (`sqlite:////data/app.db`); a Windows path becomes
    # `sqlite:///C:/…`, which SQLAlchemy reads the same way.
    return DevDatabase(path=path, url=f"sqlite:///{path.resolve().as_posix()}")


def build_dev_env(
    *,
    manifest: dict[str, Any],
    app_port: int,
    platform_base_url: str,
    app_id: str | None,
    db: DevDatabase,
    base_env: dict[str, str] | None = None,
    model_base_url: str | None = None,
    model_api_key: str | None = None,
) -> dict[str, str]:
    """The child environment: the shell's, with the platform names on top.

    Platform-owned names **override** whatever the shell had (the reserved
    prefixes are the platform's, `lifecycle.RESERVED_ENV_PREFIXES`, plus the
    model face's three), and the login key is removed from its own name.
    Nothing else is filtered: `BISHENG_APP_START` and the developer's own
    variables pass through, the same way the hosted entrypoint honours them.

    `model_base_url` is `whoami.model_base_url` verbatim. Both it and
    `model_api_key` have to be present for the three model names to be set:
    half a wiring (an address with no credential, or a credential pointed
    nowhere) is what produces a confusing 401 instead of a clear "this platform
    has no model face".
    """
    env = dict(os.environ if base_env is None else base_env)
    env.pop(LOGIN_KEY_ENV, None)
    base_path = ""
    env.update(
        {
            "BISHENG_APP_DB_URL": db.url,
            "BISHENG_APP_DB_PATH": str(db.path),
            "BISHENG_APP_ID": app_id or "",
            "BISHENG_APP_SLUG": str(manifest.get("slug") or ""),
            "BISHENG_APP_VERSION": DEV_VERSION,
            "BISHENG_APP_VERSION_ID": DEV_VERSION,
            "BISHENG_PLATFORM_API_BASE": platform_base_url,
            "PORT": str(app_port),
            "BISHENG_APP_PORT": str(app_port),
            # Empty under `dev`, `/apps/{slug}` hosted — the name is the
            # contract, the value is environment specific (INV-32 / D5.2).
            "BISHENG_APP_BASE_PATH": base_path,
            "BISHENG_APP_HEALTH_PATH": DEFAULT_HEALTH_PATH,
            # entrypoint.sh.j2 exports, spelled the same way it spells them.
            "UVICORN_ROOT_PATH": base_path,
            "STREAMLIT_SERVER_BASE_URL_PATH": base_path.lstrip("/"),
            "GRADIO_ROOT_PATH": base_path,
            "FORWARDED_ALLOW_IPS": env.get("FORWARDED_ALLOW_IPS") or "*",
        }
    )
    base_url = (model_base_url or "").strip()
    if base_url and model_api_key:
        env.update(
            {
                "OPENAI_BASE_URL": base_url,
                "OPENAI_API_KEY": model_api_key,
                "BISHENG_MODEL_BASE_URL": base_url,
            }
        )
    else:
        for name in MODEL_FACE_ENV_NAMES:
            env.pop(name, None)
    return env


# ---- start command ------------------------------------------------------------


@dataclass(frozen=True)
class StartCommand:
    """What to run and where it came from — `display` is what gets printed."""

    argv: list[str]
    source: str

    @property
    def display(self) -> str:
        return " ".join(self.argv)


def resolve_start_command(root: Path, *, environ: dict[str, str] | None = None) -> StartCommand:
    """Same resolution order as the hosted image's `entrypoint.sh.j2`.

    `BISHENG_APP_START` → `Procfile` `web:` line → `main.py` → `app.py`. Anything
    else is refused with the same four options the hosted entrypoint prints
    (its exit 78), so a project that starts locally is one that starts hosted.
    A shell string is run through `/bin/sh -c` exactly as the entrypoint does;
    a script is run with the interpreter running this CLI.
    """
    env = os.environ if environ is None else environ
    explicit = (env.get("BISHENG_APP_START") or "").strip()
    if explicit:
        return StartCommand(argv=_shell(explicit), source="BISHENG_APP_START")

    procfile = Path(root) / "Procfile"
    if procfile.is_file():
        for line in procfile.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("web:"):
                command = line[len("web:") :].strip()
                if command:
                    return StartCommand(argv=_shell(command), source="Procfile web:")
                break

    for candidate in ("main.py", "app.py"):
        if (Path(root) / candidate).is_file():
            return StartCommand(argv=[sys.executable, candidate], source=candidate)

    raise CliError(
        "找不到应用的启动方式",
        exit_code=EXIT_LOCAL_INVALID,
        next_step="提供以下任意一种：环境变量 BISHENG_APP_START、项目根 Procfile 的 web: 行、main.py 或 app.py"
        "（托管环境按同一顺序解析，本地找不到线上也起不来）。",
    )


def _shell(command: str) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", command]
    return ["/bin/sh", "-c", command]


def pick_free_port(*, exclude: int | None = None) -> int:
    """An unused loopback port for the app process (the proxy owns the public one)."""
    for _ in range(10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port != exclude:
            return port
    raise CliError(
        "无法为应用进程挑选空闲端口",
        exit_code=EXIT_LOCAL_INVALID,
        next_step="用 --app-port 显式指定一个未被占用的端口。",
    )

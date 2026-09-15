"""T043 — the project-local database and the same-named environment (AC-26 / AC-27).

The env names are the F054 contract (`contracts-runtime-manager.md` §5); the
cross-check against `runtime_manager.lifecycle.build_env` lives in
`test_platform_contract.py`. What this file pins is the behaviour around them:
platform names win over the shell, the key never enters, the database persists
and can never be packaged, and the start command resolves like the hosted
entrypoint.
"""

from __future__ import annotations

import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest

from bisheng_cli import devdb, ignore, packaging
from bisheng_cli.errors import EXIT_LOCAL_INVALID, CliError
from tests.helpers.platform_mock import FAKE_KEY

MANIFEST = {"name": "表单问卷小应用", "runtime": "python3.11", "port": 8080, "slug": "survey"}


def _env(project: Path, **overrides) -> dict[str, str]:
    db = devdb.prepare_dev_db(project)
    kwargs = {
        "manifest": MANIFEST,
        "app_port": 51234,
        "platform_base_url": "http://platform.test",
        "app_id": "app-1",
        "db": db,
        "base_env": {},
    }
    kwargs.update(overrides)
    return devdb.build_dev_env(**kwargs)


def test_env_carries_exactly_the_contract_names_plus_framework_exports(sample_project: Path) -> None:
    env = _env(sample_project)
    assert set(env) == set(devdb.PLATFORM_ENV_NAMES) | set(devdb.FRAMEWORK_ENV_NAMES)
    assert env["PORT"] == env["BISHENG_APP_PORT"] == "51234"
    assert env["BISHENG_APP_BASE_PATH"] == "" and env["UVICORN_ROOT_PATH"] == "" and env["GRADIO_ROOT_PATH"] == ""
    assert env["STREAMLIT_SERVER_BASE_URL_PATH"] == "" and env["FORWARDED_ALLOW_IPS"] == "*"
    assert env["BISHENG_APP_SLUG"] == "survey" and env["BISHENG_APP_ID"] == "app-1"
    assert env["BISHENG_APP_VERSION"] == "dev" and env["BISHENG_APP_VERSION_ID"] == "dev"
    assert env["BISHENG_PLATFORM_API_BASE"] == "http://platform.test"
    assert env["BISHENG_APP_HEALTH_PATH"] == "/"
    assert env["BISHENG_APP_DB_URL"].startswith("sqlite:///") and env["BISHENG_APP_DB_PATH"].endswith("app.db")


def test_platform_names_override_the_shell_and_the_key_never_enters(sample_project: Path) -> None:
    shell = {
        "PATH": "/usr/bin",
        "PORT": "1",
        "BISHENG_APP_DB_URL": "sqlite:///elsewhere.db",
        "BISHENG_PLATFORM_API_BASE": "http://wrong.test",
        "BISHENG_API_KEY": FAKE_KEY,
        "MY_OWN_SETTING": "kept",
        "BISHENG_APP_START": "python serve.py",
    }
    env = _env(sample_project, base_env=shell)
    assert env["PATH"] == "/usr/bin" and env["MY_OWN_SETTING"] == "kept"
    assert env["PORT"] == "51234" and env["BISHENG_PLATFORM_API_BASE"] == "http://platform.test"
    assert env["BISHENG_APP_DB_URL"] != "sqlite:///elsewhere.db"
    assert env["BISHENG_APP_START"] == "python serve.py"  # not ours to override
    assert "BISHENG_API_KEY" not in env
    assert FAKE_KEY not in "".join(env.values())
    # The reserved prefixes are the hosted runtime's; every name we set is under one.
    assert all(name.startswith(devdb.RESERVED_ENV_PREFIXES) for name in devdb.PLATFORM_ENV_NAMES)


def test_db_lives_under_dot_bisheng_dev_and_persists_across_runs(sample_project: Path) -> None:
    first = devdb.prepare_dev_db(sample_project)
    assert first.path == sample_project / ".bisheng" / "dev" / "app.db"
    assert first.path.is_file()
    conn = sqlite3.connect(first.path)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('kept')")
    conn.commit()
    conn.close()
    second = devdb.prepare_dev_db(sample_project)  # a restart
    assert second == first
    assert sqlite3.connect(second.path).execute("SELECT v FROM t").fetchone() == ("kept",)


def test_db_url_is_the_four_slash_absolute_form() -> None:
    db = devdb.DevDatabase(path=Path("/tmp/x/app.db"), url="sqlite:////tmp/x/app.db")
    assert db.url == f"sqlite:///{db.path.as_posix()}"


def test_db_never_enters_the_upload_package(sample_project: Path, tmp_path: Path) -> None:
    # AC-26 / AC-32: `.bisheng/` is a hard exclude — `!` cannot bring it back.
    devdb.prepare_dev_db(sample_project)
    (sample_project / ".bishengignore").write_text("!.bisheng/\n!*.db\n", encoding="utf-8")
    result = ignore.collect_files(sample_project)
    assert not [p for p in result.files if ".bisheng/" in str(p) or str(p).endswith("app.db")]
    stat = packaging.build_package(sample_project, result, tmp_path / "pkg.tar.gz")
    assert stat.entry_count > 0
    with tarfile.open(tmp_path / "pkg.tar.gz") as tar:
        assert not [m.name for m in tar.getmembers() if ".bisheng/" in m.name or m.name.endswith("app.db")]


# ---- start command (entrypoint.sh.j2 order) ---------------------------------


def test_start_resolution_order_matches_the_hosted_entrypoint(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(CliError) as excinfo:
        devdb.resolve_start_command(root, environ={})
    assert excinfo.value.exit_code == EXIT_LOCAL_INVALID
    for option in ("BISHENG_APP_START", "Procfile", "main.py", "app.py"):
        assert option in excinfo.value.next_step

    (root / "app.py").write_text("", encoding="utf-8")
    assert devdb.resolve_start_command(root, environ={}).argv == [sys.executable, "app.py"]

    (root / "main.py").write_text("", encoding="utf-8")
    assert devdb.resolve_start_command(root, environ={}).source == "main.py"

    (root / "Procfile").write_text("worker: python w.py\nweb: uvicorn app:app --port $PORT\n", encoding="utf-8")
    start = devdb.resolve_start_command(root, environ={})
    assert start.source == "Procfile web:" and start.argv[-1] == "uvicorn app:app --port $PORT"

    start = devdb.resolve_start_command(root, environ={"BISHENG_APP_START": "python custom.py"})
    assert start.source == "BISHENG_APP_START" and start.argv[-1] == "python custom.py"
    assert start.display.endswith("python custom.py")


def test_pick_free_port_avoids_the_proxy_port() -> None:
    port = devdb.pick_free_port(exclude=1)
    assert 1024 < port < 65536 and port != 1

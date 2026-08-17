"""Module-level import smoke.

Every import below runs at collection time, deliberately — not inside a fixture
or a function body. A dependency that resolved to a version whose API moved
breaks at import, and if the only imports live inside test bodies that break can
hide behind mocks and still leave a wheel that dies on `bisheng --help`.

This repo has already paid for that once: `fastapi>=0.115` with no ceiling
resolved to 0.121 in development (69 tests green) and to 0.141 in production,
where the removed `add_websocket_route` killed the process at import. The upper
bounds in pyproject.toml and this file are the two halves of that fix.
"""

from __future__ import annotations

import httpx
import yaml

import bisheng_cli
import bisheng_cli.cli
import bisheng_cli.commands
import bisheng_cli.credentials
import bisheng_cli.errors
import bisheng_cli.http
import bisheng_cli.ignore
import bisheng_cli.main
import bisheng_cli.output
import bisheng_cli.packaging
import bisheng_cli.project
from bisheng_cli.cli import build_parser
from bisheng_cli.main import main


def test_console_script_entry_point_is_importable_and_callable() -> None:
    # `[project.scripts] bisheng = "bisheng_cli.main:main"` — this is the exact
    # symbol pip wires the shell command to.
    assert callable(main)
    assert build_parser().prog == "bisheng"


def test_declared_runtime_dependencies_expose_the_api_we_use() -> None:
    # Not "is it installed" but "does this version still have the entry points
    # this CLI calls at module scope".
    assert hasattr(httpx, "MockTransport") and hasattr(httpx, "Timeout")
    assert hasattr(yaml, "safe_load")


def test_version_is_declared_once() -> None:
    # Everything that reports a version — --version, the compatibility probe, the
    # artifacts manifest — has to read this one attribute. A second literal
    # somewhere is how the download endpoint starts advertising a version that
    # is not the one inside the wheel.
    assert bisheng_cli.cli.__version__ is bisheng_cli.__version__
    assert bisheng_cli.http.__version__ is bisheng_cli.__version__
    assert bisheng_cli.__version__.count(".") == 2

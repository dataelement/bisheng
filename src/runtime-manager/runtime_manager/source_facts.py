"""What a runtime template needs to know about the unpacked source (T092).

The manifest carries ``runtime`` and ``port`` and nothing about how the app is
built or started — by design (F055: no ``command`` / ``entry`` field). So the
facts a template branches on are read from the project files themselves,
**here, at render time**, rather than by shell tests inside the image:

* the rendered Dockerfile then *states* what it does (``npm ci --omit=dev`` or
  no npm at all), which is what a failed build's log tail has to be read
  against;
* an app with no dependencies never invokes a package manager, so an
  air-gapped host builds it with only the base image;
* a source tree the template cannot serve fails at ``render_dockerfile`` with a
  sentence, not at ``docker_build`` with "COPY failed: no source files".

Each inspector may also *materialise* a file the Dockerfile unconditionally
COPYs (``requirements.txt``, ``package.json``): the classic builder has no
optional-COPY, and a wildcard that matches nothing is an error there.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: Lockfiles that make ``npm ci`` (reproducible, refuses drift) the right verb.
NODE_LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json")

#: Where a static package keeps its entry page, most explicit first. ``dist/``
#: and ``build/`` are soft-excluded by the CLI packager (``bisheng_cli.ignore``)
#: and come back with a ``!dist/`` line in ``.bishengignore`` — the error below
#: says so, because "I ran vite build and the platform says no index.html" is
#: the failure this ordering produces.
STATIC_ROOT_CANDIDATES = (".", "dist", "build", "public")

NODE_INSTALL_NONE = "none"
NODE_INSTALL_CI = "ci"
NODE_INSTALL_INSTALL = "install"

#: Stub written when a node app ships no package.json. ``private`` keeps npm
#: from ever treating the stub as publishable; nothing else is inferred from it.
NODE_PACKAGE_STUB = '{\n  "private": true\n}\n'


class SourceFactsError(ValueError):
    """The source tree cannot be built with this runtime's template."""


def _python_facts(context_dir: Path) -> dict[str, Any]:
    requirements = context_dir / "requirements.txt"
    if not requirements.exists():
        # Materialise it so the Dockerfile needs no optional-COPY trick, which
        # BuildKit and the classic builder disagree about.
        requirements.write_text("", encoding="utf-8")
    return {}


def _node_facts(context_dir: Path) -> dict[str, Any]:
    package_json = context_dir / "package.json"
    if not package_json.is_file():
        package_json.write_text(NODE_PACKAGE_STUB, encoding="utf-8")
        return {"node": {"install": NODE_INSTALL_NONE, "build": False}}

    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceFactsError(f"package.json is not valid JSON: {exc}") from exc
    if not isinstance(package, dict):
        raise SourceFactsError("package.json must contain a JSON object")

    dependencies = _mapping(package.get("dependencies"))
    dev_dependencies = _mapping(package.get("devDependencies"))
    scripts = _mapping(package.get("scripts"))
    has_build = bool(scripts.get("build"))

    if not dependencies and not dev_dependencies:
        install = NODE_INSTALL_NONE
    elif any((context_dir / name).is_file() for name in NODE_LOCKFILES):
        install = NODE_INSTALL_CI
    else:
        install = NODE_INSTALL_INSTALL
    # A build script with nothing installed is still a build: `tsc` may come
    # from devDependencies, but `node scripts/build.js` needs nothing.
    return {"node": {"install": install, "build": has_build}}


def _static_facts(context_dir: Path) -> dict[str, Any]:
    for candidate in STATIC_ROOT_CANDIDATES:
        if (context_dir / candidate / "index.html").is_file():
            return {"static_root": candidate}
    raise SourceFactsError(
        "the static runtime needs an index.html at the package root or in one of "
        + ", ".join(f"{name}/" for name in STATIC_ROOT_CANDIDATES if name != ".")
        + " — dist/ and build/ are left out of the package by default; add a `!dist/` "
        "line to .bishengignore to ship a built bundle"
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


SOURCE_INSPECTORS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "python3.11": _python_facts,
    "node20": _node_facts,
    "static": _static_facts,
}


def source_facts(runtime: str, context_dir: Path) -> dict[str, Any]:
    """Render-context additions for ``runtime``, read from the unpacked source.

    Raises :class:`SourceFactsError` when the tree cannot be built with that
    runtime's template; the builder reports it at the ``render_dockerfile``
    stage, where the message names the fix.
    """
    inspector = SOURCE_INSPECTORS.get(runtime)
    if inspector is None:
        return {}
    return inspector(Path(context_dir))

"""Template matrix — node20 / static next to python3.11 (T092, AC-15).

Two things are pinned here that ``test_build`` does not cover:

* **The security baseline is one baseline, not three.** Every runtime renders
  to a non-root ``USER``, an exec-form ``ENTRYPOINT`` as the last instruction,
  the shared ``/usr/local/bin/bisheng-healthcheck`` probe path that
  ``lifecycle.build_container_payload`` hard-codes, and classic-builder syntax
  only. A new template that forgets one of these fails here, before 114 ever
  builds it.
* **What the template does is decided from the source tree, at render time.**
  ``source_facts`` reads package.json / index.html and the rendered Dockerfile
  *states* the outcome (``npm ci --omit=dev``, ``COPY dist/``); the tests below
  read the same bytes a failed build's log would be read against.

Whether the images actually build and start is a real-daemon question — see
``test_real_image_builds_and_runs`` in ``test_build`` and the 114 manual check
in ``docs/architecture/14-app-factory-deployment.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_manager.builder import BASE_IMAGES, TEMPLATES_DIR, discover_runtimes, render_build_context
from runtime_manager.source_facts import (
    NODE_INSTALL_CI,
    NODE_INSTALL_INSTALL,
    NODE_INSTALL_NONE,
    NODE_PACKAGE_STUB,
    SourceFactsError,
    source_facts,
)

PORT = 8080

#: Instructions the classic daemon builder rejects; BuildKit-only syntax must
#: never reach a template (114 / 信创 build through the plain builder).
BUILDKIT_ONLY = ("COPY --chmod", "ADD --chmod", "<<EOF", "<<'EOF'", "RUN --mount", "# syntax=")


def _tree(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _render(runtime: str, tree: Path) -> dict[str, str]:
    """Exactly what ``BuildService._stage_render`` does: facts first, then render."""
    return render_build_context(runtime, {"port": PORT, **source_facts(runtime, tree)})


def _minimal_source(runtime: str) -> dict[str, str]:
    return {
        "python3.11": {"main.py": "print('hi')\n"},
        "node20": {"server.js": "// app\n"},
        "static": {"index.html": "<html></html>\n"},
    }[runtime]


def _dockerfile_instructions(dockerfile: str) -> list[str]:
    """Logical instructions (continuation lines joined, comments dropped)."""
    joined = dockerfile.replace("\\\n", " ")
    return [line.strip() for line in joined.splitlines() if line.strip() and not line.lstrip().startswith("#")]


# ---------------------------------------------------------------------------
# one baseline for every runtime
# ---------------------------------------------------------------------------


def test_every_runtime_has_a_base_image_and_every_base_image_a_runtime():
    """The pre-pull list (readonly preflight) is derived from this pairing."""
    assert set(discover_runtimes()) == set(BASE_IMAGES)


@pytest.mark.parametrize("runtime", sorted(BASE_IMAGES))
def test_security_baseline_is_identical_across_runtimes(runtime, tmp_path):
    files = _render(runtime, _tree(tmp_path / runtime, _minimal_source(runtime)))
    dockerfile = files["Dockerfile"]
    instructions = _dockerfile_instructions(dockerfile)

    assert instructions[0] == f"FROM {BASE_IMAGES[runtime]}"
    # Non-root, and never back to root afterwards.
    user_lines = [line for line in instructions if line.startswith("USER ")]
    assert user_lines == ["USER bisheng"]
    assert "10001" in dockerfile  # the fixed uid the data volume is chowned for
    # exec-form entrypoint as the last instruction: pid 1 is the app, SIGTERM lands.
    assert instructions[-1] == 'ENTRYPOINT ["/usr/local/bin/bisheng-app-entrypoint"]'
    assert not any(line.startswith("CMD ") for line in instructions)
    # The probe path lifecycle.build_container_payload hard-codes, in every image.
    assert any(
        line.startswith("HEALTHCHECK") and line.endswith('CMD ["/usr/local/bin/bisheng-healthcheck"]')
        for line in instructions
    )
    assert f"EXPOSE {PORT}" in instructions
    assert f"PORT={PORT}" in dockerfile and f"BISHENG_APP_PORT={PORT}" in dockerfile
    # AC-17: /data is the one persistent writable path, owned by the app user.
    assert "chown bisheng:bisheng /data" in dockerfile
    # Instructions only — the header comment is allowed to *mention* the forbidden syntax.
    body = "\n".join(instructions)
    for token in BUILDKIT_ONLY:
        assert token not in body, f"{runtime}: {token!r} is BuildKit-only"
    assert not dockerfile.startswith("# syntax=")


@pytest.mark.parametrize("runtime", sorted(BASE_IMAGES))
def test_entrypoint_contract_is_identical_across_runtimes(runtime, tmp_path):
    """Same variable names as ``bisheng dev`` (INV-32), same exec discipline."""
    files = _render(runtime, _tree(tmp_path / runtime, _minimal_source(runtime)))
    entrypoint = files["entrypoint.sh"]

    assert entrypoint.startswith("#!/bin/sh\n")
    assert "set -eu" in entrypoint
    assert "BISHENG_APP_BASE_PATH" in entrypoint
    assert f"BISHENG_APP_PORT:-{PORT}" in entrypoint
    assert 'exec "$@"' in entrypoint  # an explicit command (probe, debug) wins
    assert "exec " in entrypoint


@pytest.mark.parametrize("runtime", sorted(BASE_IMAGES))
def test_every_runtime_ships_exactly_one_probe(runtime, tmp_path):
    files = _render(runtime, _tree(tmp_path / runtime, _minimal_source(runtime)))
    probes = [name for name in files if name.startswith("healthcheck.")]

    assert len(probes) == 1, files.keys()
    probe = files[probes[0]]
    assert "BISHENG_APP_HEALTH_PATH" in probe
    assert "127.0.0.1" in probe
    assert f"COPY {probes[0]} /usr/local/bin/bisheng-healthcheck" in files["Dockerfile"]


@pytest.mark.parametrize("runtime", sorted(BASE_IMAGES))
def test_render_is_deterministic(runtime, tmp_path):
    tree = _tree(tmp_path / runtime, _minimal_source(runtime))
    assert _render(runtime, tree) == _render(runtime, tree)


def test_template_dirs_carry_no_stray_files():
    """Everything in a template dir is rendered into the context — keep it deliberate."""
    for runtime in discover_runtimes():
        names = sorted(p.name for p in (TEMPLATES_DIR / runtime).iterdir())
        assert all(name.endswith(".j2") for name in names), (runtime, names)
        assert "Dockerfile.j2" in names and "entrypoint.sh.j2" in names


# ---------------------------------------------------------------------------
# node20
# ---------------------------------------------------------------------------


def test_node_without_dependencies_never_runs_npm(tmp_path):
    """No package.json at all: a stub is materialised, npm is not invoked.

    The air-gapped case — a stdlib-only ``server.js`` must build with nothing
    but the base image in reach.
    """
    tree = _tree(tmp_path / "app", {"server.js": "require('http')\n"})
    facts = source_facts("node20", tree)

    assert facts == {"node": {"install": NODE_INSTALL_NONE, "build": False, "lockfiles": []}}
    assert (tree / "package.json").read_text(encoding="utf-8") == NODE_PACKAGE_STUB
    dockerfile = render_build_context("node20", {"port": PORT, **facts})["Dockerfile"]
    instructions = _dockerfile_instructions(dockerfile)
    assert not any("npm " in line for line in instructions), instructions
    assert "COPY package.json /app/" in instructions  # the stub is there, so this always matches


def test_node_with_lockfile_uses_npm_ci_omit_dev(tmp_path):
    tree = _tree(
        tmp_path / "app",
        {
            "package.json": json.dumps({"dependencies": {"express": "^4.19"}, "scripts": {"start": "node server.js"}}),
            "package-lock.json": "{}",
            "server.js": "",
        },
    )
    facts = source_facts("node20", tree)
    assert facts["node"] == {"install": NODE_INSTALL_CI, "build": False, "lockfiles": ["package-lock.json"]}

    dockerfile = render_build_context("node20", {"port": PORT, **facts})["Dockerfile"]
    instructions = _dockerfile_instructions(dockerfile)
    # The lockfile `npm ci` was chosen for reaches the dependency layer.
    assert "COPY package.json package-lock.json /app/" in instructions
    assert "npm ci --omit=dev --no-audit --no-fund" in dockerfile
    assert "npm install" not in dockerfile
    assert "npm run build" not in dockerfile
    # The registry arrives as a build arg the Dockerfile declares, under a name
    # npm does *not* read from the environment (an empty NPM_CONFIG_REGISTRY
    # would mean "registry is empty", not "default").
    assert 'ARG BISHENG_NPM_REGISTRY=""' in dockerfile
    assert '${BISHENG_NPM_REGISTRY:+--registry "$BISHENG_NPM_REGISTRY"}' in dockerfile
    assert "NPM_CONFIG_REGISTRY" not in dockerfile.replace("# Deliberately not named NPM_CONFIG_REGISTRY", "")


def test_node_without_lockfile_falls_back_to_npm_install(tmp_path):
    tree = _tree(tmp_path / "app", {"package.json": json.dumps({"dependencies": {"koa": "^2"}})})
    facts = source_facts("node20", tree)
    assert facts["node"]["install"] == NODE_INSTALL_INSTALL
    assert facts["node"]["lockfiles"] == []

    dockerfile = render_build_context("node20", {"port": PORT, **facts})["Dockerfile"]
    assert "npm install --omit=dev --no-audit --no-fund" in dockerfile
    assert "COPY package.json /app/" in _dockerfile_instructions(dockerfile)


@pytest.mark.parametrize(
    ("present", "expected_copy"),
    [
        (["npm-shrinkwrap.json"], "COPY package.json npm-shrinkwrap.json /app/"),
        (["package-lock.json", "npm-shrinkwrap.json"], "COPY package.json package-lock.json npm-shrinkwrap.json /app/"),
    ],
)
def test_node_every_lockfile_that_selects_npm_ci_is_copied(tmp_path, present, expected_copy):
    """A shrinkwrap alone selects ``npm ci`` — so it must be in the layer too.

    A ``package*.json`` wildcard would have picked ``npm ci`` from the facts and
    then run it in a directory without the lockfile, which npm refuses.
    """
    files = {"package.json": json.dumps({"dependencies": {"koa": "^2"}})}
    files.update(dict.fromkeys(present, "{}"))
    facts = source_facts("node20", _tree(tmp_path / "app", files))
    assert facts["node"]["install"] == NODE_INSTALL_CI
    assert facts["node"]["lockfiles"] == present

    instructions = _dockerfile_instructions(render_build_context("node20", {"port": PORT, **facts})["Dockerfile"])
    assert expected_copy in instructions
    assert any(line.startswith("RUN") and "npm ci " in line for line in instructions)


def test_node_build_script_installs_dev_deps_then_prunes(tmp_path):
    """Vite / Next / tsc: build with the toolchain, ship without it."""
    tree = _tree(
        tmp_path / "app",
        {
            "package.json": json.dumps(
                {
                    "dependencies": {"next": "^14"},
                    "devDependencies": {"typescript": "^5"},
                    "scripts": {"build": "next build", "start": "next start"},
                }
            ),
            "package-lock.json": "{}",
        },
    )
    facts = source_facts("node20", tree)
    assert facts["node"] == {"install": NODE_INSTALL_CI, "build": True, "lockfiles": ["package-lock.json"]}

    dockerfile = render_build_context("node20", {"port": PORT, **facts})["Dockerfile"]
    instructions = _dockerfile_instructions(dockerfile)
    install = next(i for i, line in enumerate(instructions) if "npm ci --include=dev" in line)
    copy_all = next(i for i, line in enumerate(instructions) if line == "COPY --chown=bisheng:bisheng . /app")
    build = next(i for i, line in enumerate(instructions) if "npm run build" in line)
    assert install < copy_all < build, instructions
    assert "npm prune --omit=dev" in instructions[build]
    # Build args stay build-time only: the build step runs before USER drops.
    assert instructions.index("USER bisheng") > build


def test_node_dev_only_dependencies_still_install_for_a_build(tmp_path):
    tree = _tree(
        tmp_path / "app",
        {"package.json": json.dumps({"devDependencies": {"vite": "^5"}, "scripts": {"build": "vite build"}})},
    )
    assert source_facts("node20", tree)["node"] == {"install": NODE_INSTALL_INSTALL, "build": True, "lockfiles": []}


def test_node_invalid_package_json_is_a_render_error(tmp_path):
    tree = _tree(tmp_path / "app", {"package.json": "{not json"})
    with pytest.raises(SourceFactsError, match=r"package\.json is not valid JSON"):
        source_facts("node20", tree)


def test_node_runtime_writes_only_under_tmp(tmp_path):
    """ReadonlyRootfs (AC-17): npm's cache/log dir is pinned to the tmpfs."""
    files = _render("node20", _tree(tmp_path / "app", _minimal_source("node20")))
    assert "NPM_CONFIG_CACHE=/tmp/.npm" in files["Dockerfile"]
    assert "NPM_CONFIG_CACHE" in files["entrypoint.sh"]


def test_node_entrypoint_start_resolution_order(tmp_path):
    """Most explicit first, and every winner is exec'd (pid 1 is the app)."""
    entrypoint = _render("node20", _tree(tmp_path / "app", _minimal_source("node20")))["entrypoint.sh"]
    order = [
        entrypoint.index("BISHENG_APP_START"),
        entrypoint.index("/app/Procfile"),
        entrypoint.index("pkg_field scripts.start"),
        entrypoint.index("pkg_field main"),
        entrypoint.index("for candidate in server.js index.js app.js main.js"),
    ]
    assert order == sorted(order)
    assert "exec /bin/sh -c" in entrypoint
    assert 'exec node "/app/$candidate"' in entrypoint
    # `npm start` is deliberately not a step: it would sit between pid 1 and the app.
    assert "npm start" not in entrypoint.split("# Start command resolution")[1].split("if [", 1)[1]
    # D5.2: the base path reaches the app under both the contract name and the
    # conventional node spelling.
    assert 'export BASE_PATH="$BISHENG_APP_BASE_PATH"' in entrypoint
    assert "/app/node_modules/.bin" in entrypoint
    assert "exit 78" in entrypoint


def test_node_probe_is_node_not_curl(tmp_path):
    """node:20-slim has neither curl nor wget; the probe is a node script."""
    files = _render("node20", _tree(tmp_path / "app", _minimal_source("node20")))
    probe = files["healthcheck.js"]
    assert probe.startswith("#!/usr/bin/env node\n")
    assert 'require("http")' in probe
    assert f'"{PORT}"' in probe
    assert "statusCode < 500" in probe


# ---------------------------------------------------------------------------
# static
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("files", "expected_root"),
    [
        ({"index.html": ""}, "."),
        ({"dist/index.html": ""}, "dist"),
        ({"build/index.html": ""}, "build"),
        ({"public/index.html": ""}, "public"),
        # The package root wins when it carries its own page.
        ({"index.html": "", "dist/index.html": ""}, "."),
        ({"dist/index.html": "", "public/index.html": ""}, "dist"),
    ],
)
def test_static_root_detection(tmp_path, files, expected_root):
    tree = _tree(tmp_path / "app", files)
    facts = source_facts("static", tree)
    assert facts == {"static_root": expected_root}
    dockerfile = render_build_context("static", {"port": PORT, **facts})["Dockerfile"]
    assert f"COPY --chown=bisheng:bisheng {expected_root}/ /app/www/" in dockerfile


def test_static_without_an_index_names_the_fix(tmp_path):
    tree = _tree(tmp_path / "app", {"dist/app.js": "", "README.md": ""})
    with pytest.raises(SourceFactsError) as excinfo:
        source_facts("static", tree)
    message = str(excinfo.value)
    assert "index.html" in message
    assert "dist/" in message and "!dist/" in message and ".bishengignore" in message


def test_static_nginx_config_survives_a_read_only_rootfs(tmp_path):
    """Every path nginx writes is under /tmp; the config itself is rendered there."""
    files = _render("static", _tree(tmp_path / "app", _minimal_source("static")))
    conf = files["nginx.conf"]

    assert "pid /tmp/nginx/nginx.pid;" in conf
    for directive in (
        "client_body_temp_path",
        "proxy_temp_path",
        "fastcgi_temp_path",
        "uwsgi_temp_path",
        "scgi_temp_path",
    ):
        assert f"{directive} /tmp/nginx/" in conf, directive
    assert "user " not in conf  # master already runs unprivileged; the directive would only warn
    assert "root /app/www;" in conf
    assert "listen __PORT__;" in conf  # substituted at start, from the injected PORT

    entrypoint = files["entrypoint.sh"]
    assert 'sed "s|__PORT__|$PORT|g" /etc/bisheng/nginx.conf.tmpl > /tmp/nginx/nginx.conf' in entrypoint
    assert "exec nginx -c /tmp/nginx/nginx.conf -g 'daemon off;'" in entrypoint
    assert "COPY nginx.conf /etc/bisheng/nginx.conf.tmpl" in files["Dockerfile"]


def test_static_nginx_config_keeps_the_app_under_its_prefix(tmp_path):
    """D5.2: redirects stay relative, the build context is never served, SPA fallback."""
    conf = _render("static", _tree(tmp_path / "app", _minimal_source("static")))["nginx.conf"]

    assert "absolute_redirect off;" in conf
    assert "port_in_redirect off;" in conf
    assert "server_tokens off;" in conf
    # The rendered build files sit next to the app when the root is served.
    for name in ("Dockerfile", "entrypoint\\.sh", "nginx\\.conf", "healthcheck\\.sh", "bisheng-app\\.yaml"):
        assert name in conf
    assert "location ~ /\\." in conf
    assert "try_files $uri $uri/ /index.html;" in conf
    assert "try_files $uri =404;" in conf  # assets never fall back to the shell


def test_static_probe_is_busybox_wget(tmp_path):
    files = _render("static", _tree(tmp_path / "app", _minimal_source("static")))
    probe = files["healthcheck.sh"]
    assert probe.startswith("#!/bin/sh\n")
    assert 'wget -q -T 2 -O /dev/null "$url"' in probe
    assert f"PORT:-{PORT}" in probe


def test_static_template_runs_no_package_manager(tmp_path):
    dockerfile = _render("static", _tree(tmp_path / "app", _minimal_source("static")))["Dockerfile"]
    for verb in ("apk add", "apt-get", "pip ", "npm "):
        assert verb not in dockerfile
    assert "ARG " not in dockerfile  # nothing to resolve → no build args to declare

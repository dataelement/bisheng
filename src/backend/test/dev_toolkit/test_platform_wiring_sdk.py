"""F057 T035 — the SDK increment to the「平台能力接线」pack (AC-26 … AC-36).

The pack itself is F053's and its structural guards live in ``test_skill_packs.py``;
this file pins only what F057 added — the SDK usage in the identity chapter, the
two new chapters, the SDK example, and the self-check's SDK steps.

Two of the assertions below are **regressions in the other direction**: the
identity chapter must still come first and still open with the silent-failure
warning, and the model chapter must still carry no literal address. Inserting
chapters is exactly the edit that breaks those, so they are asserted here as
well as in F053's file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bisheng.dev_toolkit.domain.services.artifact_service import SKILLS_DIR

WIRING = SKILLS_DIR / "platform-wiring"
SKILL_MD = WIRING / "SKILL.md"
EXAMPLE_SDK = WIRING / "example-sdk"
SELFCHECK = WIRING / "selfcheck.py"


def _body() -> str:
    return SKILL_MD.read_text(encoding="utf-8").split("---", 2)[2]


def _chapters(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return [(part.split("\n", 1)[0].strip(), part.split("\n", 1)[1] if "\n" in part else "") for part in parts]


def _chapter(keyword: str) -> str:
    for heading, content in _chapters(_body()):
        if keyword in heading:
            return content
    raise AssertionError(f"no chapter matching {keyword!r}")


def _anchor(heading: str) -> str:
    """GitHub's heading → anchor rule, reduced to what these headings use."""
    slug = heading.strip().lower().replace("`", "")
    slug = re.sub(r"[^\w一-鿿 \-]", "", slug)
    return slug.strip().replace(" ", "-")


def test_auth_chapter_still_first_with_warning_block_after_edit():
    """Regression: inserting chapters must not move the identity chapter off the top."""
    chapters = _chapters(_body())
    heading, content = chapters[0]
    assert "身份" in heading
    first_para = content.strip().split("\n\n", 1)[0]
    assert first_para.startswith(">") and "⚠️" in first_para and "静默" in first_para


def test_auth_chapter_teaches_the_sdk_one_liner_and_the_wrong_ways():
    chapter = _chapter("身份")
    assert "auth.current_user()" in chapter
    # The three ways to hand the request to the SDK — nothing else is taught.
    for hook in ("ASGIMiddleware", "WSGIMiddleware", "auth.bind("):
        assert hook in chapter
    # The wrong ways, each named: roll your own sign-in, hand-assemble identity
    # from the headers, parse the visitor credential yourself.
    for wrong in ("自建登录页", "自己读头", "自己解析"):
        assert wrong in chapter
    # No identity means an exception, never None — the whole point of the chapter.
    assert "PlatformIdentityMissingError" in chapter and "不返回 `None`" in chapter
    # The placeholder F053 left for this feature is gone.
    assert "随后续版本补齐" not in SKILL_MD.read_text(encoding="utf-8")


def test_retrieve_chapter_states_per_user_semantics_and_the_local_difference():
    chapter = _chapter("检索")
    for term in ("白名单", "可见范围", "fail-closed", "本地看得少", "真实账号"):
        assert term in chapter, term
    # Examples must pass knowledge base ids: the facade still requires them.
    assert "knowledge_base_ids=" in chapter
    # Both credentials are named, and so is the rule that makes them unswappable
    # — the settled F055 contract, which the chapter must not simplify away.
    assert "BISHENG_APP_TOKEN" in chapter
    assert "没有 owner 兜底" in chapter
    # The honest note is about `bisheng dev`, not about the hosted half: hosted
    # retrieval is merged, and saying otherwise sends the developer chasing a
    # platform that is working.
    assert "本地 `bisheng dev` 还不能" in chapter and "换密钥没有用" in chapter
    assert "尚未上线" not in chapter, "hosted retrieval is live; that claim is stale"
    # And the error the developer actually meets first under `dev` is listed.
    assert "AppCredentialMissingError" in chapter


def test_storage_chapter_states_the_local_online_difference_and_the_quota_rule():
    chapter = _chapter("附件存储")
    for term in ("不计", "配额", "不进", "上传包", "直链"):
        assert term in chapter, term
    # Six functions, no sweep-everything operation, no URL-returning one.
    for fn in ("storage.put", "storage.get", "storage.stat", "storage.list", "storage.delete", "storage.open"):
        assert fn in chapter, fn
    assert "没有「清空" in chapter
    assert "BISHENG_APP_STORAGE_MAX_FILE_MB" in chapter


def test_model_chapter_teaches_the_injected_names_and_no_literal_address():
    """Regression, re-aimed (F057 T035a): F051 shipped, so「暂未提供」would now be a lie.

    The three things a reader must come away with are the injected variable
    names, that the callable range is the manifest declaration rather than the
    tenant, and that the visitor credential has to be forwarded by the app or
    the call record loses its user dimension. The no-URL assertion stays exactly
    as it was — AC-30 keeps one outward spelling of the address either way.
    """
    chapter = _chapter("模型")
    assert "暂未提供" not in chapter
    for env_name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "BISHENG_MODEL_BASE_URL"):
        assert env_name in chapter, env_name
    # The declaration is the range hosted, and an undeclared model is refused.
    assert "capabilities" in chapter and "26215" in chapter
    # Forwarding the visitor credential, and the local case where it is refused.
    assert "X-BiSheng-Access-Token" in chapter and "26204" in chapter
    assert not re.search(r"https?://", chapter)


def test_no_sdk_wrapper_is_taught_for_models_or_the_app_database():
    """AC-30: the SDK has three capability modules and gains no fourth by prose."""
    text = SKILL_MD.read_text(encoding="utf-8")
    for invented in ("bisheng_sdk.chat", "bisheng_sdk.appdb", "bisheng_sdk.llm", "bisheng_sdk.db"):
        assert invented not in text
    # And the reason is stated, so the next person does not "helpfully" add one.
    assert "平台特有" in text


def test_toc_entries_and_anchors_both_resolve():
    """Renumbering chapters without fixing the table of contents is the classic miss."""
    body = _body()
    headings = [heading for heading, _ in _chapters(body)]
    anchors = {_anchor(heading) for heading in headings}
    # Only numbered chapters belong in the TOC (「参考」is an appendix).
    numbered = [heading for heading in headings if re.match(r"^\d+\. ", heading)]

    entries = re.findall(r"^\d+\. \[([^\]]+)\]\(#([^)]+)\)", body, re.MULTILINE)
    assert len(entries) == len(numbered), f"TOC has {len(entries)} entries for {len(numbered)} chapters"
    for _label, anchor in entries:
        assert anchor in anchors, f"TOC anchor #{anchor} matches no heading; headings are {sorted(anchors)}"

    # In-body cross references too (the SDK section links to the last chapter).
    for anchor in re.findall(r"\]\(#([^)]+)\)", body):
        assert anchor in anchors, f"dangling in-body anchor #{anchor}"


def test_example_sdk_manifest_is_valid_and_declares_a_knowledge_base():
    """The SDK example declares the capability it uses — that is what the whitelist is."""
    import yaml

    from bisheng.app_publish.domain.schemas.app_manifest import SUPPORTED_RUNTIMES, AppManifest

    manifest = AppManifest(**yaml.safe_load((EXAMPLE_SDK / "bisheng-app.yaml").read_text(encoding="utf-8")))

    assert manifest.runtime in SUPPORTED_RUNTIMES
    assert not manifest.capabilities.is_empty()
    assert manifest.capabilities.knowledge_bases and not manifest.capabilities.models


def test_example_sdk_requirements_carry_the_sdk():
    """A hosted build resolves this line from the platform's own index (AC-02)."""
    requirements = (EXAMPLE_SDK / "requirements.txt").read_text(encoding="utf-8")
    lines = [line.strip() for line in requirements.splitlines() if line.strip() and not line.startswith("#")]
    assert "bisheng-sdk" in lines
    # The stdlib-only example next door stays stdlib-only; this is the other one.
    stdlib_example = (WIRING / "example" / "requirements.txt").read_text(encoding="utf-8")
    assert not [line for line in stdlib_example.splitlines() if line.strip() and not line.startswith("#")]


def test_example_sdk_separates_a_missing_app_credential_from_a_platform_outage():
    """An un-injected ``BISHENG_APP_TOKEN`` is an environment fault, not a 502.

    Folded into the catch-all it would read as "the platform is down" — which is
    exactly the wrong thing to chase, since the fix is to redeploy the app (or,
    locally, to wait for `bisheng dev` to inject it).
    """
    source = (EXAMPLE_SDK / "main.py").read_text(encoding="utf-8")
    ask = source.split('@app.post("/ask")', 1)[1].split("@app.", 1)[0]

    assert "errors.AppCredentialMissingError" in ask
    # Declared before the catch-all, or Python never reaches it.
    assert ask.index("errors.AppCredentialMissingError") < ask.index("errors.BishengSdkError")


def test_example_sdk_healthz_does_not_call_auth():
    """A probe request carries no identity, so an auth call there fails the whole app."""
    source = (EXAMPLE_SDK / "main.py").read_text(encoding="utf-8")
    handler = source.split('@app.get("/healthz")', 1)[1].split("@app.get", 1)[0]
    assert "current_user" not in handler
    # And the example rolls no auth of its own.
    for forbidden in ("password", "set-cookie", "jwt"):
        assert forbidden not in source.lower(), forbidden


def test_example_sdk_keeps_the_manifest_and_the_code_on_one_knowledge_base_id():
    """Two places, one fact — the example says so and must itself be consistent."""
    import yaml

    manifest = yaml.safe_load((EXAMPLE_SDK / "bisheng-app.yaml").read_text(encoding="utf-8"))
    declared = [str(ref.get("id") or ref.get("name")) for ref in manifest["capabilities"]["knowledge_bases"]]
    source = (EXAMPLE_SDK / "main.py").read_text(encoding="utf-8")
    used = re.search(r"KNOWLEDGE_BASE_IDS = \[([^\]]*)\]", source).group(1)
    assert [item.strip() for item in used.split(",") if item.strip()] == declared


# ---- self-check ---------------------------------------------------------------


def _selfcheck_module():
    """Import ``selfcheck.py`` by path — it is a shipped script, not a package module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_wiring_selfcheck", SELFCHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selfcheck_probes_the_dev_entry_not_the_app_port(tmp_path, monkeypatch):
    """The one address that proves nothing is the app's own port.

    ``bisheng dev`` listens twice: the mini proxy (the local entry, which injects
    the ``X-BiSheng-*`` headers) and the application process. ``PORT`` /
    ``BISHENG_APP_PORT`` name the **second** one, so a probe sent there arrives
    with no injected header at all — the check would fail for every developer
    and then blame them for "connecting straight to the app port".
    """
    selfcheck = _selfcheck_module()
    (tmp_path / "bisheng-app.yaml").write_text("name: x\nruntime: python3.11\nport: 8080\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BISHENG_APP_PORT", "54321")
    monkeypatch.setenv("PORT", "54321")
    monkeypatch.delenv(selfcheck.DEV_ENTRY_ENV, raising=False)

    resolved = selfcheck.dev_entry_url(None)

    assert resolved == "http://127.0.0.1:8080"
    assert "54321" not in resolved


def test_selfcheck_entry_url_prefers_the_explicit_address(tmp_path, monkeypatch):
    """``bisheng dev --port`` makes the manifest's port wrong, so it can be overridden."""
    selfcheck = _selfcheck_module()
    (tmp_path / "bisheng-app.yaml").write_text("port: 8080\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert selfcheck.dev_entry_url("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
    # A bare host:port is accepted too — that is how the address is printed.
    assert selfcheck.dev_entry_url("127.0.0.1:3000/") == "http://127.0.0.1:3000"

    monkeypatch.setenv(selfcheck.DEV_ENTRY_ENV, "http://127.0.0.1:3100")
    assert selfcheck.dev_entry_url(None) == "http://127.0.0.1:3100"


def test_selfcheck_skips_the_sdk_trio_when_there_is_no_dev_session(tmp_path, monkeypatch, capsys):
    """No entry address is "not applicable here", the same as the app-db check.

    A hard failure would mean the recommended invocation (``python selfcheck.py``
    from a plain shell) can never exit 0, which trains developers to ignore it.
    """
    selfcheck = _selfcheck_module()
    monkeypatch.chdir(tmp_path)  # no bisheng-app.yaml anywhere above it
    monkeypatch.delenv(selfcheck.DEV_ENTRY_ENV, raising=False)

    assert selfcheck.check_sdk_auth(selfcheck.dev_entry_url(None)) is None
    printed = capsys.readouterr().out
    assert "跳过" in printed and "bisheng dev" in printed


def _run_selfcheck(home: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(SELFCHECK)], capture_output=True, text=True, env=env)


def test_selfcheck_without_any_config_fails_with_a_sentence(tmp_path):
    """AC-28: a missing precondition reads as one line and a next step, never a traceback."""
    home = tmp_path / "home"
    home.mkdir()

    result = _run_selfcheck(home)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "下一步" in combined
    assert "Traceback" not in combined


class _FakePlatform(BaseHTTPRequestHandler):
    """Answers the two endpoints the self-check reads, nothing else."""

    versions_payload: dict = {}

    def do_GET(self):
        if self.path.startswith("/api/v2/auth/whoami"):
            payload = {"status_code": 200, "data": {"actor_name": "自检服务账号"}}
        elif self.path.startswith("/api/v1/dev-toolkit/versions"):
            payload = self.versions_payload
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output clean
        return


def test_selfcheck_reports_an_incompatible_sdk_with_both_versions(tmp_path):
    """AC-03: the refusal names this SDK, the platform's floor, and how to fix it."""
    _FakePlatform.versions_payload = {
        "status_code": 200,
        "data": {"sdk": {"version": "9.9.9", "min_compatible": "9.9.9"}},
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakePlatform)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        home = tmp_path / "home"
        (home / ".bisheng").mkdir(parents=True)
        (home / ".bisheng" / "credentials.json").write_text(
            json.dumps(
                {
                    "current": "local",
                    "profiles": {"local": {"base_url": base_url, "api_key": "bs-sak-" + "x" * 43}},
                }
            ),
            encoding="utf-8",
        )
        # A stand-in package: the backend venv does not (and must not) depend on
        # the SDK, and the version comparison is all this branch reads.
        stub = tmp_path / "stub"
        (stub / "bisheng_sdk").mkdir(parents=True)
        (stub / "bisheng_sdk" / "__init__.py").write_text(
            textwrap.dedent('''
                """Stand-in for the real package; only __version__ is read here."""

                __version__ = "0.1.0"
            '''),
            encoding="utf-8",
        )

        result = _run_selfcheck(home, {"PYTHONPATH": str(stub)})
    finally:
        server.shutdown()

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "0.1.0" in combined and "9.9.9" in combined
    assert "pip install" in combined
    assert "Traceback" not in combined


def test_selfcheck_says_which_command_installs_the_sdk_when_it_is_absent(tmp_path):
    """Not installed is not a crash: the script names the install command and the index."""
    _FakePlatform.versions_payload = {"status_code": 200, "data": {"sdk": None}}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakePlatform)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        home = tmp_path / "home"
        (home / ".bisheng").mkdir(parents=True)
        (home / ".bisheng" / "credentials.json").write_text(
            json.dumps(
                {
                    "current": "local",
                    "profiles": {"local": {"base_url": base_url, "api_key": "bs-sak-" + "y" * 43}},
                }
            ),
            encoding="utf-8",
        )
        result = _run_selfcheck(home)
    finally:
        server.shutdown()

    combined = result.stdout + result.stderr
    assert "pip install" in combined and "/api/v1/dev-toolkit/simple/" in combined
    assert "Traceback" not in combined


def test_sdk_guide_endpoint_serves_this_very_file():
    """决议-7: one source for the guide and the pack, asserted from both ends."""
    from bisheng.dev_toolkit.domain.services import artifact_service

    assert artifact_service.read_sdk_guide() == SKILL_MD.read_text(encoding="utf-8")

import importlib.util
import io
import json
import os
import stat
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

import pytest

from bisheng.common.errcode.open_api import ApiCredentialNotFoundError
from bisheng.open_api.domain.services.skill_pack_service import SkillPackService

SCRIPT_FILE = Path(__file__).resolve().parents[2] / "bisheng/open_api/skill_packs/knowledge-search/scripts/search.py"
OK_LIST_BODY = b'{"status_code": 200, "status_message": "ok", "data": {"data": [], "page_size": 1, "has_more": false}}'
KEY = "bs-pat-abcdefgh1234"


def test_pack_is_deterministic_safe_and_instance_rendered():
    first = SkillPackService.build("knowledge-search", base_url="https://example.test/base")
    second = SkillPackService.build("knowledge-search", base_url="https://example.test/base")
    assert first == second

    with ZipFile(BytesIO(first)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        skill = archive.read("knowledge-search/SKILL.md").decode()
        security = archive.read("knowledge-search/SECURITY.md").decode()
        script = archive.read("knowledge-search/scripts/search.py").decode()

    assert "https://example.test/base" in skill
    assert "https://example.test" in security
    assert "/api/v2/filelib/retrieve" in script
    assert "KNOWLEDGE_API_KEY" in script
    assert "X-Bisheng" not in first.decode("latin-1")
    # White-label guard: no brand strings may ship inside the pack (F066 iter 2).
    whole = first.decode("latin-1")
    assert "BiSheng" not in whole and "BISHENG" not in whole
    assert "__pycache__" not in whole


def test_pack_name_is_allowlisted():
    with pytest.raises(ApiCredentialNotFoundError):
        SkillPackService.build("../secret", base_url="https://example.test")


# ── F066 · pack teaches list-first, Chinese triggers, and error passthrough ──
# 覆盖 AC: AC-R4


def test_pack_ships_rendered_api_reference_and_list_first_flow():
    payload = SkillPackService.build("knowledge-search", base_url="https://example.test/base")

    with ZipFile(BytesIO(payload)) as archive:
        skill = archive.read("knowledge-search/SKILL.md").decode()
        api = archive.read("knowledge-search/references/api.md").decode()
        script = archive.read("knowledge-search/scripts/search.py").decode()

    # Chinese trigger words in the routing description (PRD §4.10.8 must-have 1).
    assert "知识库" in skill and "检索" in skill
    # List-first workflow: the agent learns where knowledge-base IDs come from.
    assert "--list-knowledge-bases" in skill and "--list-knowledge-bases" in script
    # The API reference is instance-rendered and covers pagination, citations
    # and the 26044 data-scope action (PRD §4.10.8 must-haves 2/3 + D21).
    assert "https://example.test/base" in api
    assert "next_cursor" in api and "chunk_index" in api and "26044" in api


# ── script harness ───────────────────────────────────────────────────────────


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(request, code: int, body: bytes) -> HTTPError:
    return HTTPError(request.full_url, code, "error", None, io.BytesIO(body))


def _load_script(path: Path = SCRIPT_FILE, name: str = "bisheng_skill_search"):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch, tmp_path):
    """Source-tree script with a clean environment and a throw-away config home."""
    monkeypatch.delenv("KNOWLEDGE_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # non-tty, empty: nothing piped
    return _load_script()


def _run(module, monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["search.py", *argv])
    return module.main()


def _capture(module, monkeypatch, body: bytes = OK_LIST_BODY):
    """Install a urlopen fake that records requests and answers `body`."""
    seen = []

    def fake(request, timeout=30):
        seen.append(request)
        return _Response(body)

    monkeypatch.setattr(module, "urlopen", fake)
    return seen


def _store_path(module) -> Path:
    return Path(module._credentials_path())


def _write_store(module, profiles: dict) -> Path:
    path = _store_path(module)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "profiles": profiles}), encoding="utf-8")
    return path


def test_script_surfaces_business_error_bodies(script, monkeypatch, capsys):
    def deny(request, timeout=30):
        raise _http_error(
            request,
            403,
            b'{"status_code": 26044, "status_message": "restricted", "data": {"scope": "personal_only"}}',
        )

    monkeypatch.setattr(script, "urlopen", deny)
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "bs-pat-test")

    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--query", "q", "--knowledge-base-id", "7") == 1
    err = capsys.readouterr().err
    assert "HTTP 403" in err and "26044" in err  # the business code reaches the agent


# ── credentials: env override, file fallback, actionable errors ─────────────


def test_rendered_script_bakes_the_instance_base_url(monkeypatch, tmp_path, capsys):
    payload = SkillPackService.build("knowledge-search", base_url="https://example.test/base")
    with ZipFile(BytesIO(payload)) as archive:
        rendered = archive.read("knowledge-search/scripts/search.py").decode()
    assert 'DEFAULT_BASE_URL = "https://example.test/base"' in rendered

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    target = tmp_path / "rendered_search.py"
    target.write_text(rendered, encoding="utf-8")
    module = _load_script(target, name="bisheng_skill_search_rendered")
    assert module._default_base_url() == "https://example.test/base"  # sentinel did not eat itself

    monkeypatch.setenv("KNOWLEDGE_API_KEY", KEY)
    seen = _capture(module, monkeypatch)
    assert _run(module, monkeypatch, "--list-knowledge-bases", "space") == 0  # no --base-url needed
    assert seen[0].full_url.startswith("https://example.test/base/api/v2/filelib/?")


def test_source_script_requires_base_url_while_placeholder_is_unrendered(script, monkeypatch, capsys):
    assert script._default_base_url() == ""
    monkeypatch.setenv("KNOWLEDGE_API_KEY", KEY)
    assert _run(script, monkeypatch, "--list-knowledge-bases", "space") == 2
    assert "--base-url" in capsys.readouterr().err


def test_environment_key_wins_and_the_store_is_not_even_read(script, monkeypatch):
    path = _store_path(script)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")  # would raise if read
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "bs-pat-fromenv0001")
    seen = _capture(script, monkeypatch)

    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "doc") == 0
    assert seen[0].get_header("Authorization") == "Bearer bs-pat-fromenv0001"


def test_store_profile_is_found_by_normalised_base_url(script, monkeypatch):
    _write_store(script, {"https://kb.test": {"base_url": "https://kb.test", "api_key": KEY}})
    seen = _capture(script, monkeypatch)

    assert _run(script, monkeypatch, "--base-url", "HTTPS://KB.TEST/", "--query", "q", "--knowledge-base-id", "7") == 0
    assert seen[0].get_header("Authorization") == f"Bearer {KEY}"
    assert seen[0].full_url == "https://kb.test/api/v2/filelib/retrieve"


def test_missing_key_message_gives_the_next_command_not_a_hunt(script, monkeypatch, capsys):
    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "space") == 2
    err = capsys.readouterr().err
    assert "No API key for https://kb.test" in err
    assert "--configure --base-url <platform address> --api-key <key>" in err
    assert str(_store_path(script)) in err
    assert "KNOWLEDGE_API_KEY" in err

    # Another platform saved in the file is listed (non-secret) with the --base-url hint,
    # but never used implicitly: retrieved content must not be able to redirect the key.
    _write_store(script, {"https://other.test": {"base_url": "https://other.test", "api_key": KEY}})
    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "space") == 2
    err = capsys.readouterr().err
    assert "https://other.test" in err and "--base-url" in err and KEY not in err


def test_unauthorized_error_names_the_key_source(script, monkeypatch, capsys):
    _write_store(script, {"https://kb.test": {"base_url": "https://kb.test", "api_key": "bs-pat-freshkey0001"}})
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "bs-pat-stalekey0001")

    def deny(request, timeout=30):
        raise _http_error(request, 401, b'{"status_code": 26002, "status_message": "revoked"}')

    monkeypatch.setattr(script, "urlopen", deny)
    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "space") == 1
    err = capsys.readouterr().err
    assert "26002" in err and "environment variable KNOWLEDGE_API_KEY" in err and "Unset" in err

    monkeypatch.delenv("KNOWLEDGE_API_KEY")
    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "space") == 1
    err = capsys.readouterr().err
    assert "credentials file" in err and "--configure" in err


def test_corrupt_store_is_reported_with_its_path(script, monkeypatch, capsys):
    path = _store_path(script)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "space") == 2
    assert str(path) in capsys.readouterr().err


# ── --configure ──────────────────────────────────────────────────────────────


def test_configure_saves_a_verified_key_owner_only(script, monkeypatch, capsys):
    seen = _capture(script, monkeypatch)
    assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "HTTPS://KB.test/") == 0
    assert seen[0].full_url == "https://kb.test/api/v2/filelib/?page_size=1"

    path = _store_path(script)
    store = json.loads(path.read_text(encoding="utf-8"))
    profile = store["profiles"]["https://kb.test"]
    assert profile["api_key"] == KEY and profile["key_mask"] == "bs-pat-********1234"
    assert profile["base_url"] == "https://kb.test" and profile["saved_at"]
    assert store["default_base_url"] == "https://kb.test"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    captured = capsys.readouterr()
    assert "bs-pat-********1234" in captured.out and str(path) in captured.out
    assert "abcdefgh" not in captured.out + captured.err  # plaintext never printed

    # The saved key is what later calls use, with no environment at all.
    seen.clear()
    assert _run(script, monkeypatch, "--base-url", "https://kb.test", "--list-knowledge-bases", "space") == 0
    assert seen[0].get_header("Authorization") == f"Bearer {KEY}"


def test_configure_refuses_a_rejected_key_or_a_wrong_address(script, monkeypatch, capsys):
    cases = [
        (401, b'{"status_code": 26002, "status_message": "revoked"}'),
        (404, b'{"detail": "Not Found"}'),
    ]
    for code, body in cases:
        monkeypatch.setattr(
            script,
            "urlopen",
            lambda request, timeout=30, c=code, b=body: (_ for _ in ()).throw(_http_error(request, c, b)),
        )
        assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "https://kb.test") == 1
        assert not _store_path(script).exists()
        assert "not saved" in capsys.readouterr().err

    # A web page (SPA catch-all answering 200 for any path) is not the API.
    _capture(script, monkeypatch, body=b"<!doctype html><html></html>")
    assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "https://kb.test") == 1
    assert not _store_path(script).exists()
    assert "--base-url" in capsys.readouterr().err


def test_configure_keeps_an_intact_key_behind_a_business_restriction(script, monkeypatch, capsys):
    def restricted(request, timeout=30):
        raise _http_error(request, 403, b'{"status_code": 26044, "status_message": "restricted", "data": {}}')

    monkeypatch.setattr(script, "urlopen", restricted)
    assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "https://kb.test") == 0
    assert json.loads(_store_path(script).read_text())["profiles"]["https://kb.test"]["api_key"] == KEY
    assert "26044" in capsys.readouterr().out  # body passed through for references/api.md handling


def test_configure_saves_but_warns_when_the_platform_is_unreachable(script, monkeypatch, capsys):
    def down(request, timeout=30):
        raise URLError("connection refused")

    monkeypatch.setattr(script, "urlopen", down)
    assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "https://kb.test") == 0
    assert _store_path(script).exists()
    err = capsys.readouterr().err
    assert "not verified" in err and "--list-knowledge-bases" in err


def test_configure_never_clobbers_a_corrupt_store(script, monkeypatch, capsys):
    path = _store_path(script)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{not json")
    _capture(script, monkeypatch)
    assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "https://kb.test") == 2
    assert path.read_bytes() == b"{not json"
    assert str(path) in capsys.readouterr().err


def test_configure_rejects_placeholders_and_hides_mistyped_flags(script, monkeypatch, capsys):
    _capture(script, monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("<key>\n"))
    assert _run(script, monkeypatch, "--configure", "--base-url", "https://kb.test") == 2
    assert not _store_path(script).exists()
    assert "placeholder" in capsys.readouterr().err

    # A mistyped flag must not make argparse echo the key back.
    assert _run(script, monkeypatch, "--configure", "--api_key", KEY, "--base-url", "https://kb.test") == 2
    err = capsys.readouterr().err
    assert "--api_key" in err and KEY not in err and "abcdefgh" not in err


def test_configure_warns_when_a_different_environment_key_shadows_the_file(script, monkeypatch, capsys):
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "bs-pat-stalekey0001")
    _capture(script, monkeypatch)
    assert _run(script, monkeypatch, "--configure", "--api-key", KEY, "--base-url", "https://kb.test") == 0
    err = capsys.readouterr().err
    assert "takes precedence" in err and "stalekey" not in err


# ── platform address: the browser origin saved by --configure beats the baked one ──


def _rendered_module(monkeypatch, tmp_path, baked: str):
    """Pack script as downloaded behind a proxy that hid the browser address."""
    monkeypatch.delenv("KNOWLEDGE_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    payload = SkillPackService.build("knowledge-search", base_url=baked)
    with ZipFile(BytesIO(payload)) as archive:
        rendered = archive.read("knowledge-search/scripts/search.py").decode()
    target = tmp_path / "rendered_behind_proxy.py"
    target.write_text(rendered, encoding="utf-8")
    return _load_script(target, name="bisheng_skill_search_behind_proxy")


def test_saved_browser_address_heals_a_wrongly_baked_pack(monkeypatch, tmp_path, capsys):
    module = _rendered_module(monkeypatch, tmp_path, "http://backend:7860")
    seen = _capture(module, monkeypatch)

    # The setup command copied from the platform page carries the browser origin.
    assert _run(module, monkeypatch, "--configure", "--base-url", "https://KB.example.com/", "--api-key", KEY) == 0
    assert seen[-1].full_url == "https://kb.example.com/api/v2/filelib/?page_size=1"
    assert "Later calls use https://kb.example.com by default" in capsys.readouterr().out

    # A new session without --base-url goes to the saved address, not the baked one.
    seen.clear()
    assert _run(module, monkeypatch, "--query", "q", "--knowledge-base-id", "7") == 0
    assert seen[0].full_url == "https://kb.example.com/api/v2/filelib/retrieve"
    assert seen[0].get_header("Authorization") == f"Bearer {KEY}"


def test_explicit_base_url_still_beats_the_saved_default(monkeypatch, tmp_path):
    module = _rendered_module(monkeypatch, tmp_path, "http://backend:7860")
    _write_store(
        module,
        {
            "https://kb.example.com": {"base_url": "https://kb.example.com", "api_key": KEY},
            "https://other.example.com": {"base_url": "https://other.example.com", "api_key": KEY},
        },
    )
    path = _store_path(module)
    store = json.loads(path.read_text(encoding="utf-8"))
    store["default_base_url"] = "https://kb.example.com"
    path.write_text(json.dumps(store), encoding="utf-8")
    seen = _capture(module, monkeypatch)

    assert _run(module, monkeypatch, "--base-url", "https://other.example.com", "--list-knowledge-bases", "doc") == 0
    assert seen[0].full_url.startswith("https://other.example.com/api/v2/filelib/?")


def test_a_bad_saved_default_falls_back_to_the_baked_address(monkeypatch, tmp_path):
    module = _rendered_module(monkeypatch, tmp_path, "https://baked.example.com")
    _write_store(module, {"https://baked.example.com": {"base_url": "https://baked.example.com", "api_key": KEY}})
    path = _store_path(module)
    store = json.loads(path.read_text(encoding="utf-8"))
    store["default_base_url"] = "not a url"
    path.write_text(json.dumps(store), encoding="utf-8")
    seen = _capture(module, monkeypatch)

    assert _run(module, monkeypatch, "--list-knowledge-bases", "space") == 0
    assert seen[0].full_url.startswith("https://baked.example.com/api/v2/filelib/?")


def test_corrupt_store_without_base_url_still_reports_the_file(monkeypatch, tmp_path, capsys):
    module = _rendered_module(monkeypatch, tmp_path, "https://baked.example.com")
    path = _store_path(module)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert _run(module, monkeypatch, "--list-knowledge-bases", "space") == 2
    assert str(path) in capsys.readouterr().err

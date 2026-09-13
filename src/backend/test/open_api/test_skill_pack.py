from io import BytesIO
from zipfile import ZipFile

import pytest

from bisheng.common.errcode.open_api import ApiCredentialNotFoundError
from bisheng.open_api.domain.services.skill_pack_service import SkillPackService


def test_pack_is_deterministic_safe_and_instance_rendered():
    first = SkillPackService.build("bisheng-knowledge-search", base_url="https://example.test/base")
    second = SkillPackService.build("bisheng-knowledge-search", base_url="https://example.test/base")
    assert first == second

    with ZipFile(BytesIO(first)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        skill = archive.read("bisheng-knowledge-search/SKILL.md").decode()
        security = archive.read("bisheng-knowledge-search/SECURITY.md").decode()
        script = archive.read("bisheng-knowledge-search/scripts/search.py").decode()

    assert "https://example.test/base" in skill
    assert "https://example.test" in security
    assert "/api/v2/filelib/retrieve" in script
    assert "BISHENG_API_KEY" in script
    assert "X-Bisheng" not in first.decode("latin-1")


def test_pack_name_is_allowlisted():
    with pytest.raises(ApiCredentialNotFoundError):
        SkillPackService.build("../secret", base_url="https://example.test")


# ── F066 · pack teaches list-first, Chinese triggers, and error passthrough ──
# 覆盖 AC: AC-R4


def test_pack_ships_rendered_api_reference_and_list_first_flow():
    payload = SkillPackService.build("bisheng-knowledge-search", base_url="https://example.test/base")

    with ZipFile(BytesIO(payload)) as archive:
        skill = archive.read("bisheng-knowledge-search/SKILL.md").decode()
        api = archive.read("bisheng-knowledge-search/references/api.md").decode()
        script = archive.read("bisheng-knowledge-search/scripts/search.py").decode()

    # Chinese trigger words in the routing description (PRD §4.10.8 must-have 1).
    assert "知识库" in skill and "检索" in skill
    # List-first workflow: the agent learns where knowledge-base IDs come from.
    assert "--list-knowledge-bases" in skill and "--list-knowledge-bases" in script
    # The API reference is instance-rendered and covers pagination, citations
    # and the 26044 data-scope action (PRD §4.10.8 must-haves 2/3 + D21).
    assert "https://example.test/base" in api
    assert "next_cursor" in api and "chunk_index" in api and "26044" in api


def test_script_surfaces_business_error_bodies(monkeypatch, capsys, tmp_path):
    import importlib.util
    import io
    import sys
    from pathlib import Path
    from urllib.error import HTTPError

    script_file = (
        Path(__file__).resolve().parents[2]
        / "bisheng/open_api/skill_packs/bisheng-knowledge-search/scripts/search.py"
    )
    spec = importlib.util.spec_from_file_location("bisheng_skill_search", script_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def deny(request, timeout=30):
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            None,
            io.BytesIO(b'{"status_code": 26044, "status_message": "restricted", "data": {"scope": "personal_only"}}'),
        )

    monkeypatch.setattr(module, "urlopen", deny)
    monkeypatch.setenv("BISHENG_API_KEY", "bs-pat-test")
    monkeypatch.setattr(
        sys,
        "argv",
        ["search.py", "--base-url", "https://kb.test", "--query", "q", "--knowledge-base-id", "7"],
    )

    assert module.main() == 1
    err = capsys.readouterr().err
    assert "HTTP 403" in err and "26044" in err  # the business code reaches the agent

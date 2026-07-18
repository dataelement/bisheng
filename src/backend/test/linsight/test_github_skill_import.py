"""F035 GitHub-import increment — unit tests for the URL parser, the recursive
GitHub fetcher (httpx mocked) and SkillService.create_from_github (which reuses
the same _create chain as the upload path). DAO is an in-memory fake; disk IO
runs against a tmp SkillStore."""

from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.common.errcode.linsight import (
    SkillFileTooLargeError,
    SkillGitHubFetchError,
    SkillGitHubRateLimitError,
    SkillGitHubUrlInvalidError,
    SkillNameDuplicateError,
    SkillValidationError,
)
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.services import github_skill_fetcher as fetcher_module
from bisheng.linsight.domain.services import skill_service as service_module
from bisheng.linsight.domain.services.github_skill_fetcher import (
    GithubTarget,
    fetch_skill_files,
    parse_github_url,
)
from bisheng.linsight.domain.services.skill_store import MAX_BUNDLE_SIZE, SKILL_MD, SkillStore

TENANT = 1
USER = 7

SKILL_MD_BYTES = (
    "---\nname: demo-skill\ndescription: demo desc\nmetadata:\n  display-name: 演示技能\n---\n\n# body\n"
).encode()


# --------------------------------------------------------------------------- #
# parse_github_url
# --------------------------------------------------------------------------- #
class TestParseGithubUrl:
    def test_tree_url_with_path(self):
        t = parse_github_url("https://github.com/owner/repo/tree/main/skills/demo")
        assert t == GithubTarget(owner="owner", repo="repo", ref="main", subpath="skills/demo")

    def test_tree_url_without_path(self):
        t = parse_github_url("https://github.com/owner/repo/tree/dev")
        assert t == GithubTarget(owner="owner", repo="repo", ref="dev", subpath="")

    def test_bare_repo_defaults_to_empty_ref_and_root(self):
        t = parse_github_url("https://github.com/owner/repo")
        assert t == GithubTarget(owner="owner", repo="repo", ref="", subpath="")

    def test_bare_repo_strips_git_suffix_and_trailing_slash(self):
        t = parse_github_url("https://github.com/owner/repo.git/")
        assert t == GithubTarget(owner="owner", repo="repo", ref="", subpath="")

    def test_blob_pointing_to_skill_md_takes_parent_dir(self):
        t = parse_github_url("https://github.com/owner/repo/blob/main/skills/demo/SKILL.md")
        assert t == GithubTarget(owner="owner", repo="repo", ref="main", subpath="skills/demo")

    def test_blob_pointing_to_other_file_rejected(self):
        with pytest.raises(SkillGitHubUrlInvalidError):
            parse_github_url("https://github.com/owner/repo/blob/main/skills/demo/readme.md")

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/owner/repo/tree/main/skills/demo",
            "https://raw.githubusercontent.com/owner/repo/main/SKILL.md",
            "ftp://github.com/owner/repo",
            "https://github.com/owner",  # missing repo
            "not a url",
        ],
    )
    def test_invalid_urls_rejected(self, url):
        with pytest.raises(SkillGitHubUrlInvalidError):
            parse_github_url(url)

    def test_slash_branch_is_misparsed_documented_limitation(self):
        # Known limitation (matches upstream): the first segment after `tree` is the
        # ref, so a `release/v2` branch parses wrongly rather than raising.
        t = parse_github_url("https://github.com/owner/repo/tree/release/v2/foo")
        assert t.ref == "release" and t.subpath == "v2/foo"


# --------------------------------------------------------------------------- #
# fetch_skill_files (httpx mocked)
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        return self._handler(url, params)


def _patch_httpx(monkeypatch, handler):
    monkeypatch.setattr(fetcher_module.httpx, "AsyncClient", lambda *a, **k: _FakeClient(handler))


CONTENTS = "https://api.github.com/repos/o/r/contents"
RAW = "https://raw.githubusercontent.com/o/r/main"


class TestFetchSkillFiles:
    async def test_happy_path_recurses_and_keeps_bytes(self, monkeypatch):
        def handler(url, params=None):
            if url == f"{CONTENTS}/skills/demo":
                return _FakeResponse(
                    json_data=[
                        {
                            "name": "SKILL.md",
                            "type": "file",
                            "size": len(SKILL_MD_BYTES),
                            "download_url": f"{RAW}/skills/demo/SKILL.md",
                        },
                        {"name": "scripts", "type": "dir", "path": "skills/demo/scripts"},
                    ]
                )
            if url == f"{CONTENTS}/skills/demo/scripts":
                return _FakeResponse(
                    json_data=[
                        {"name": "a.py", "type": "file", "size": 8, "download_url": f"{RAW}/skills/demo/scripts/a.py"},
                    ]
                )
            if url == f"{RAW}/skills/demo/SKILL.md":
                return _FakeResponse(content=SKILL_MD_BYTES)
            if url == f"{RAW}/skills/demo/scripts/a.py":
                return _FakeResponse(content=b"print(1)")
            raise AssertionError(f"unexpected url: {url}")

        _patch_httpx(monkeypatch, handler)
        files = await fetch_skill_files(GithubTarget("o", "r", "main", "skills/demo"))
        assert files == {SKILL_MD: SKILL_MD_BYTES, "scripts/a.py": b"print(1)"}

    async def test_missing_skill_md_at_root_rejected(self, monkeypatch):
        def handler(url, params=None):
            return _FakeResponse(
                json_data=[
                    {"name": "readme.md", "type": "file", "size": 4, "download_url": f"{RAW}/readme.md"},
                    {"name": "sub", "type": "dir", "path": "sub"},
                ]
            )

        _patch_httpx(monkeypatch, handler)
        with pytest.raises(SkillValidationError, match=r"SKILL\.md"):
            await fetch_skill_files(GithubTarget("o", "r", "main", ""))

    async def test_404_maps_to_fetch_error(self, monkeypatch):
        _patch_httpx(monkeypatch, lambda url, params=None: _FakeResponse(status_code=404))
        with pytest.raises(SkillGitHubFetchError):
            await fetch_skill_files(GithubTarget("o", "r", "main", "skills/demo"))

    async def test_403_maps_to_rate_limit(self, monkeypatch):
        _patch_httpx(monkeypatch, lambda url, params=None: _FakeResponse(status_code=403))
        with pytest.raises(SkillGitHubRateLimitError):
            await fetch_skill_files(GithubTarget("o", "r", "main", "skills/demo"))

    async def test_oversize_rejected(self, monkeypatch):
        def handler(url, params=None):
            return _FakeResponse(
                json_data=[
                    {
                        "name": "SKILL.md",
                        "type": "file",
                        "size": MAX_BUNDLE_SIZE + 1,
                        "download_url": f"{RAW}/SKILL.md",
                    },
                ]
            )

        _patch_httpx(monkeypatch, handler)
        with pytest.raises(SkillFileTooLargeError):
            await fetch_skill_files(GithubTarget("o", "r", "main", ""))

    async def test_download_from_unexpected_host_rejected(self, monkeypatch):
        def handler(url, params=None):
            return _FakeResponse(
                json_data=[
                    {
                        "name": "SKILL.md",
                        "type": "file",
                        "size": 4,
                        "download_url": "https://evil.example.com/SKILL.md",
                    },
                ]
            )

        _patch_httpx(monkeypatch, handler)
        with pytest.raises(SkillGitHubFetchError, match="host"):
            await fetch_skill_files(GithubTarget("o", "r", "main", ""))

    async def test_transport_error_maps_to_fetch_error(self, monkeypatch):
        def handler(url, params=None):
            raise httpx.ConnectError("boom")

        _patch_httpx(monkeypatch, handler)
        with pytest.raises(SkillGitHubFetchError):
            await fetch_skill_files(GithubTarget("o", "r", "main", "skills/demo"))


# --------------------------------------------------------------------------- #
# SkillService.create_from_github (fetch mocked, real _create chain)
# --------------------------------------------------------------------------- #
class _FakeSkillDao:
    rows: dict[str, LinsightSkill] = {}
    _seq: int = 0

    @classmethod
    def reset(cls):
        cls.rows, cls._seq = {}, 0

    @classmethod
    async def create(cls, skill):
        cls._seq += 1
        skill.id = cls._seq
        cls.rows[skill.name] = skill
        return skill

    @classmethod
    async def get_by_name(cls, name):
        return cls.rows.get(name)

    @classmethod
    async def get_by_display_name(cls, display_name):
        return next((s for s in cls.rows.values() if s.display_name == display_name), None)


@pytest.fixture
def service(tmp_path, monkeypatch):
    _FakeSkillDao.reset()
    monkeypatch.setattr(service_module, "LinsightSkillDao", _FakeSkillDao)
    monkeypatch.setattr(service_module.PermissionService, "authorize", AsyncMock())
    return service_module.SkillService(store=SkillStore(root=tmp_path))


def _patch_fetch(monkeypatch, files):
    monkeypatch.setattr(service_module, "fetch_skill_files", AsyncMock(return_value=files))


class TestCreateFromGithub:
    async def test_success_reuses_create_chain(self, service, monkeypatch):
        _patch_fetch(monkeypatch, {SKILL_MD: SKILL_MD_BYTES, "scripts/a.py": b"print(1)"})
        detail = await service.create_from_github(TENANT, USER, "https://github.com/o/r/tree/main/skills/demo")
        assert detail.name == "demo-skill"
        assert detail.display_name == "演示技能"
        assert detail.source == "manual"
        assert {f.path for f in detail.files} == {SKILL_MD, "scripts/a.py"}
        service_module.PermissionService.authorize.assert_awaited_once()

    async def test_missing_skill_md_rejected(self, service, monkeypatch):
        _patch_fetch(monkeypatch, {"readme.md": b"x"})
        with pytest.raises(SkillValidationError, match=r"SKILL\.md"):
            await service.create_from_github(TENANT, USER, "https://github.com/o/r/tree/main/x")

    async def test_duplicate_rejected(self, service, monkeypatch):
        _patch_fetch(monkeypatch, {SKILL_MD: SKILL_MD_BYTES})
        await service.create_from_github(TENANT, USER, "https://github.com/o/r/tree/main/skills/demo")
        with pytest.raises(SkillNameDuplicateError):
            await service.create_from_github(TENANT, USER, "https://github.com/o/r/tree/main/skills/demo")

    async def test_invalid_url_rejected_before_fetch(self, service):
        with pytest.raises(SkillGitHubUrlInvalidError):
            await service.create_from_github(TENANT, USER, "https://gitlab.com/o/r/tree/main/x")

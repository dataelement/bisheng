"""Public Gitee directory import: URL parser, contents walk, and the create chain."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.common.errcode.linsight import (
    SkillGiteeFetchError,
    SkillGiteeRateLimitError,
    SkillGiteeUrlInvalidError,
    SkillNameDuplicateError,
    SkillValidationError,
)
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.services import github_skill_fetcher as fetcher_module
from bisheng.linsight.domain.services import skill_service as service_module
from bisheng.linsight.domain.services.github_skill_fetcher import GithubTarget, fetch_skill_files, parse_gitee_url
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 1
USER = 7
SKILL_MD_BYTES = (
    "---\nname: demo-skill\ndescription: demo desc\nmetadata:\n  display-name: 演示技能\n---\n\n# body\n"
).encode()
CONTENTS = "https://gitee.com/api/v5/repos/o/r/contents"
RAW = "https://gitee.com/o/r/raw/master"


class TestParseGiteeUrl:
    def test_tree_url_with_path(self):
        target = parse_gitee_url("https://gitee.com/owner/repo/tree/master/skills/demo")
        assert target == GithubTarget(owner="owner", repo="repo", ref="master", subpath="skills/demo", host="gitee")

    def test_www_host_and_git_suffix(self):
        target = parse_gitee_url("https://www.gitee.com/owner/repo.git/")
        assert target == GithubTarget(owner="owner", repo="repo", ref="", subpath="", host="gitee")

    def test_blob_pointing_to_skill_md_takes_parent_dir(self):
        target = parse_gitee_url("https://gitee.com/owner/repo/blob/master/skills/demo/SKILL.md")
        assert target.subpath == "skills/demo" and target.ref == "master" and target.host == "gitee"

    def test_blob_pointing_to_other_file_rejected(self):
        with pytest.raises(SkillGiteeUrlInvalidError):
            parse_gitee_url("https://gitee.com/owner/repo/blob/master/skills/demo/readme.md")

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo/tree/main/skills/demo",
            "https://gitlab.com/owner/repo",
            "ftp://gitee.com/owner/repo",
            "https://gitee.com/owner",
            "not a url",
        ],
    )
    def test_invalid_urls_rejected(self, url):
        with pytest.raises(SkillGiteeUrlInvalidError):
            parse_gitee_url(url)


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", url=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.url = url

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


class TestFetchGiteeSkillFiles:
    async def test_happy_path_follows_raw_redirect(self, monkeypatch):
        def handler(url, params=None):
            if url == f"{CONTENTS}/skills/demo":
                assert params == {"ref": "master"}
                return _FakeResponse(
                    json_data=[
                        {
                            "name": "SKILL.md",
                            "type": "file",
                            "size": len(SKILL_MD_BYTES),
                            "download_url": f"{RAW}/skills/demo/SKILL.md",
                        }
                    ]
                )
            if url == f"{RAW}/skills/demo/SKILL.md":
                return _FakeResponse(
                    content=SKILL_MD_BYTES,
                    url=httpx.URL("https://raw.giteeusercontent.com/o/r/raw/master/skills/demo/SKILL.md"),
                )
            raise AssertionError(f"unexpected url: {url}")

        _patch_httpx(monkeypatch, handler)
        files = await fetch_skill_files(GithubTarget("o", "r", "master", "skills/demo", host="gitee"))
        assert files == {SKILL_MD: SKILL_MD_BYTES}

    async def test_redirect_to_unexpected_host_rejected(self, monkeypatch):
        def handler(url, params=None):
            if "contents" in url:
                return _FakeResponse(
                    json_data=[
                        {"name": "SKILL.md", "type": "file", "size": 4, "download_url": f"{RAW}/SKILL.md"},
                    ]
                )
            return _FakeResponse(content=b"nope", url=httpx.URL("https://evil.example.com/SKILL.md"))

        _patch_httpx(monkeypatch, handler)
        with pytest.raises(SkillGiteeFetchError, match="host"):
            await fetch_skill_files(GithubTarget("o", "r", "master", "", host="gitee"))

    async def test_404_and_rate_limit(self, monkeypatch):
        _patch_httpx(monkeypatch, lambda url, params=None: _FakeResponse(status_code=404))
        with pytest.raises(SkillGiteeFetchError):
            await fetch_skill_files(GithubTarget("o", "r", "master", "skills/demo", host="gitee"))

        _patch_httpx(monkeypatch, lambda url, params=None: _FakeResponse(status_code=403))
        with pytest.raises(SkillGiteeRateLimitError):
            await fetch_skill_files(GithubTarget("o", "r", "master", "skills/demo", host="gitee"))


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
    async def get_by_name(cls, name, owner_user_id=0, **kwargs):
        row = cls.rows.get(name)
        if row is not None and getattr(row, "owner_user_id", 0) != owner_user_id:
            return None
        return row

    @classmethod
    async def get_by_display_name(cls, display_name, owner_user_id=0, **kwargs):
        return next(
            (
                s
                for s in cls.rows.values()
                if s.display_name == display_name and getattr(s, "owner_user_id", 0) == owner_user_id
            ),
            None,
        )


@pytest.fixture
def service(tmp_path, monkeypatch):
    _FakeSkillDao.reset()
    monkeypatch.setattr(service_module, "LinsightSkillDao", _FakeSkillDao)
    return service_module.SkillService(
        store=SkillStore(root=tmp_path, minio=FakeMinioStorage()),
        owner_projection=SimpleNamespace(authorize_created=AsyncMock()),
    )


class TestCreateFromGitee:
    async def test_success_reuses_create_chain(self, service, monkeypatch):
        monkeypatch.setattr(service_module, "fetch_skill_files", AsyncMock(return_value={SKILL_MD: SKILL_MD_BYTES}))
        detail = await service.create_from_gitee(TENANT, USER, "https://gitee.com/o/r/tree/master/skills/demo")
        assert detail.name == "demo-skill"
        assert detail.source == "manual"
        service._owner_projection.authorize_created.assert_awaited_once()

    async def test_duplicate_rejected(self, service, monkeypatch):
        monkeypatch.setattr(service_module, "fetch_skill_files", AsyncMock(return_value={SKILL_MD: SKILL_MD_BYTES}))
        await service.create_from_gitee(TENANT, USER, "https://gitee.com/o/r/tree/master/skills/demo")
        with pytest.raises(SkillNameDuplicateError):
            await service.create_from_gitee(TENANT, USER, "https://gitee.com/o/r/tree/master/skills/demo")

    async def test_github_url_rejected_before_fetch(self, service):
        with pytest.raises(SkillGiteeUrlInvalidError):
            await service.create_from_gitee(TENANT, USER, "https://github.com/o/r/tree/main/x")

    async def test_missing_skill_md_rejected(self, service, monkeypatch):
        monkeypatch.setattr(service_module, "fetch_skill_files", AsyncMock(return_value={"readme.md": b"x"}))
        with pytest.raises(SkillValidationError, match=r"SKILL\.md"):
            await service.create_from_gitee(TENANT, USER, "https://gitee.com/o/r/tree/master/x")

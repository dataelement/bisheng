"""F078 T07: decide whether the configured skills can run."""

from types import SimpleNamespace

import pytest

from bisheng.agent_runtime.domain.services.skill_resolver import resolve_skills
from bisheng.common.errcode.linsight import AgentSkillDeletedError, AgentSkillDisabledError


class _FakeRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def list_by_names(self, names):
        self.calls.append(list(names))
        return [row for row in self.rows if row.name in names]


def _row(name, enabled=1):
    return SimpleNamespace(name=name, enabled=enabled)


class TestResolveSkills:
    async def test_none_and_empty_mean_no_skills(self):
        repo = _FakeRepo([_row("pdf")])
        assert await resolve_skills(None, repository=repo) == []
        assert await resolve_skills([], repository=repo) == []
        assert repo.calls == []

    async def test_returns_rows_in_configured_order(self):
        repo = _FakeRepo([_row("pdf"), _row("docx")])
        rows = await resolve_skills(["docx", "pdf"], repository=repo)
        assert [row.name for row in rows] == ["docx", "pdf"]

    async def test_duplicate_names_are_collapsed(self):
        repo = _FakeRepo([_row("pdf")])
        rows = await resolve_skills(["pdf", "pdf"], repository=repo)
        assert [row.name for row in rows] == ["pdf"]

    async def test_disabled_skill_raises_11075_with_name(self):
        repo = _FakeRepo([_row("pdf"), _row("docx", enabled=0)])
        with pytest.raises(AgentSkillDisabledError) as exc_info:
            await resolve_skills(["pdf", "docx"], repository=repo)
        assert exc_info.value.code == 11075
        assert exc_info.value.kwargs["skill_name"] == "docx"
        assert "docx" in exc_info.value.message

    async def test_deleted_skill_raises_11076_with_name(self):
        repo = _FakeRepo([_row("pdf")])
        with pytest.raises(AgentSkillDeletedError) as exc_info:
            await resolve_skills(["pdf", "gone"], repository=repo)
        assert exc_info.value.code == 11076
        assert exc_info.value.kwargs["skill_name"] == "gone"

    async def test_first_unavailable_skill_in_config_order_is_reported(self):
        repo = _FakeRepo([_row("docx", enabled=0)])
        with pytest.raises(AgentSkillDeletedError) as exc_info:
            await resolve_skills(["gone", "docx"], repository=repo)
        assert exc_info.value.kwargs["skill_name"] == "gone"

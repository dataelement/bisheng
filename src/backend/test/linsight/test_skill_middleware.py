"""F035 Track D — TenantSkillsMiddleware whitelist tests (TD-3, deviation D8).

Real SKILL.md files on a tmp SKILLS_ROOT, real deepagents SkillsMiddleware
loading; only the DAO is bypassed (enabled_names passed explicitly).
Contract C3 semantics under test:

- built-in skills always pass, regardless of active_skills;
- tenant custom skills require governance-enabled AND per-run whitelist;
- active_skills == [] disables every custom skill;
- missing active_skills (non-UI callers) keeps all enabled custom skills.
"""

from unittest.mock import MagicMock

import pytest

from bisheng.linsight.domain.services import skill_middleware as mw_module
from bisheng.linsight.domain.services.skill_middleware import TenantSkillsMiddleware, make_skills_middleware
from bisheng.linsight.domain.services.skill_store import SkillStore

TENANT = 1


def _write_skill(base, name: str, display_name: str = ""):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    meta_block = f"metadata:\n  display-name: {display_name}\n" if display_name else ""
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: desc of {name}\n{meta_block}---\n\n# {name}\n",
        encoding="utf-8",
    )


@pytest.fixture
def store(tmp_path):
    s = SkillStore(root=tmp_path)
    _write_skill(s.builtin_dir(), "kernel-core")
    _write_skill(s.tenant_dir(TENANT), "biao-shu-zhuan-xie", "标书撰写")
    _write_skill(s.tenant_dir(TENANT), "he-tong-shen-yue", "合同审阅")
    _write_skill(s.tenant_dir(TENANT), "ting-yong-ji-neng", "已停用技能")
    return s


def _names(update) -> set[str]:
    return {s["name"] for s in update["skills_metadata"]}


def _run(store, enabled_names, active_skills="__missing__") -> set[str]:
    middleware = TenantSkillsMiddleware(tenant_id=TENANT, enabled_names=enabled_names, store=store)
    configurable = {} if active_skills == "__missing__" else {"active_skills": active_skills}
    update = middleware.before_agent({}, MagicMock(), {"configurable": configurable})
    return _names(update)


ENABLED = {"biao-shu-zhuan-xie", "he-tong-shen-yue"}  # ting-yong-ji-neng disabled in DB


class TestWhitelist:
    def test_whitelist_filters_custom_skills(self, store):
        assert _run(store, ENABLED, ["biao-shu-zhuan-xie"]) == {"kernel-core", "biao-shu-zhuan-xie"}

    def test_empty_whitelist_disables_all_custom_but_keeps_builtin(self, store):
        assert _run(store, ENABLED, []) == {"kernel-core"}

    def test_missing_whitelist_keeps_all_enabled(self, store):
        assert _run(store, ENABLED) == {"kernel-core", *ENABLED}

    def test_db_disabled_skill_excluded_even_if_whitelisted(self, store):
        assert _run(store, ENABLED, ["ting-yong-ji-neng", "biao-shu-zhuan-xie"]) == {
            "kernel-core",
            "biao-shu-zhuan-xie",
        }

    def test_builtin_not_affected_by_whitelist_content(self, store):
        # whitelisting the built-in name is a no-op: it always passes anyway
        assert "kernel-core" in _run(store, ENABLED, ["kernel-core"])

    def test_skip_when_state_already_loaded(self, store):
        middleware = TenantSkillsMiddleware(tenant_id=TENANT, enabled_names=ENABLED, store=store)
        # deepagents skips reloading when skills_metadata is already in state
        update = middleware.before_agent({"skills_metadata": []}, MagicMock(), {"configurable": {}})
        assert update is None

    async def test_async_path_matches_sync(self, store):
        middleware = TenantSkillsMiddleware(tenant_id=TENANT, enabled_names=ENABLED, store=store)
        update = await middleware.abefore_agent({}, MagicMock(), {"configurable": {"active_skills": []}})
        assert _names(update) == {"kernel-core"}


class TestFactory:
    async def test_make_skills_middleware_resolves_enabled_from_dao(self, store, monkeypatch):
        row = MagicMock()
        row.name = "biao-shu-zhuan-xie"

        async def fake_list_enabled():
            return [row]

        monkeypatch.setattr(mw_module.LinsightSkillDao, "list_enabled", fake_list_enabled)
        middleware = await make_skills_middleware(TENANT, store=store)
        update = middleware.before_agent({}, MagicMock(), {"configurable": {}})
        assert _names(update) == {"kernel-core", "biao-shu-zhuan-xie"}

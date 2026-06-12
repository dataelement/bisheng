"""F035 Track G — migrate_sop_to_skill script tests: pinyin slug allocation,
dedupe suffixes, oversize skip, idempotent re-run, dry-run no-write."""

import importlib.util
from pathlib import Path

import pytest

from bisheng.linsight.domain.models.linsight_sop import LinsightSOP
from bisheng.linsight.domain.services.skill_store import SkillStore, parse_skill_md
from test.linsight.test_skill_service import FakeSkillDao

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_sop_to_skill.py"
_spec = importlib.util.spec_from_file_location("migrate_sop_to_skill", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

TENANT = 1


def _sop(sop_id: int, name: str, content: str = "# SOP 正文", description: str = "已有描述", tenant_id: int = TENANT):
    return LinsightSOP(
        id=sop_id,
        name=name,
        description=description,
        user_id=7,
        content=content,
        vector_store_id="0" * 36,
        tenant_id=tenant_id,
    )


def _report() -> dict:
    return {"summary": {}, "success": [], "skipped": [], "failed": []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    FakeSkillDao.reset()
    monkeypatch.setattr(script, "LinsightSkillDao", FakeSkillDao)
    return SkillStore(root=tmp_path)


async def _run_tenant(store, sops, apply=True, no_llm=True):
    report = _report()
    await script._migrate_tenant(store, TENANT, sops, apply, no_llm, report)
    return report


class TestDedupeHelpers:
    def test_name_suffix_sequence(self):
        used = {"demo", "demo-2"}
        assert script._dedupe_name("demo", used) == ("demo-3", True)
        assert script._dedupe_name("fresh", used) == ("fresh", False)

    def test_name_suffix_respects_length_cap(self):
        base = "x" * 64
        name, renamed = script._dedupe_name(base, {base})
        assert renamed and len(name) <= 64 and name.endswith("-2")

    def test_display_name_suffix(self):
        assert script._dedupe_display_name("客户投诉处理SOP", {"客户投诉处理SOP"}) == "客户投诉处理SOP（2）"


class TestMigrateTenant:
    async def test_happy_path_chinese_name(self, env):
        report = await _run_tenant(env, [_sop(17, "标书撰写流程")])
        assert report["summary"] == {} and len(report["success"]) == 1
        entry = report["success"][0]
        assert entry["skill_name"] == "biao-shu-zhuan-xie-liu-cheng"
        assert entry["display_name"] == "标书撰写流程"
        row = FakeSkillDao.rows["biao-shu-zhuan-xie-liu-cheng"]
        assert row.source == "sop_migrated" and row.enabled
        meta, body = parse_skill_md(env.read_text(TENANT, row.name))
        assert meta["metadata"]["sop-id"] == "17"
        assert meta["metadata"]["display-name"] == "标书撰写流程"
        assert body.strip() == "# SOP 正文"

    async def test_duplicate_names_get_suffixes(self, env):
        report = await _run_tenant(env, [_sop(31, "客户投诉处理SOP"), _sop(38, "客户投诉处理SOP")])
        names = [e["skill_name"] for e in report["success"]]
        assert names == ["ke-hu-tou-su-chu-li-sop", "ke-hu-tou-su-chu-li-sop-2"]
        assert report["success"][1]["display_name"] == "客户投诉处理SOP（2）"
        assert report["success"][1]["renamed"] is True

    async def test_oversize_skipped(self, env):
        report = await _run_tenant(env, [_sop(40, "全集团制度汇编", content="x" * (script.SOP_CONTENT_LIMIT + 1))])
        assert report["skipped"][0]["reason"] == "SKIPPED_OVERSIZE"
        assert not report["success"] and not FakeSkillDao.rows

    async def test_empty_name_and_content_failed(self, env):
        report = await _run_tenant(env, [_sop(60, "", content="  ", description="")])
        assert report["failed"][0]["reason"] == "PARSE_FAILED"

    async def test_symbol_only_name_falls_back_to_sop_id(self, env):
        report = await _run_tenant(env, [_sop(61, "！！！")])
        assert report["success"][0]["skill_name"] == "sop-61"

    async def test_missing_description_fallback_no_llm(self, env):
        report = await _run_tenant(env, [_sop(52, "会议纪要整理", description="")])
        assert report["success"][0]["description_mode"] == "fallback"
        assert "会议纪要整理" in FakeSkillDao.rows["hui-yi-ji-yao-zheng-li"].description

    async def test_idempotent_rerun_reuses_names(self, env):
        sops = [_sop(17, "标书撰写流程"), _sop(31, "客户投诉处理SOP")]
        await _run_tenant(env, sops)
        rows_before = dict(FakeSkillDao.rows)
        report2 = await _run_tenant(env, sops)
        # second run overwrites the same skills — no new rows, no extra suffixes
        assert len(report2["success"]) == 2
        assert set(FakeSkillDao.rows) == set(rows_before)
        assert not any(e.get("renamed") for e in report2["success"])

    async def test_dry_run_writes_nothing(self, env):
        report = await _run_tenant(env, [_sop(17, "标书撰写流程")], apply=False)
        assert len(report["success"]) == 1
        assert not FakeSkillDao.rows
        assert not env.exists(TENANT, "biao-shu-zhuan-xie-liu-cheng")

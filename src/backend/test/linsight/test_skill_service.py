"""F035 Track D — SkillService unit tests (TD-3): validation chain, duplicates,
bundle upload, tenant-custom-only addressing. DAO is replaced with an in-memory
fake; disk IO runs against a tmp SkillStore."""

import io
import zipfile
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.linsight import (
    SkillFileTooLargeError,
    SkillNameDuplicateError,
    SkillNotFoundError,
    SkillValidationError,
)
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.schemas.skill_schema import SkillCreateForm
from bisheng.linsight.domain.services import skill_service as service_module
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import MAX_BUNDLE_SIZE, SKILL_MD, SkillStore

TENANT = 1
USER = 7


class FakeSkillDao:
    """In-memory stand-in for LinsightSkillDao (single-tenant view)."""

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
    async def update(cls, skill):
        cls.rows[skill.name] = skill
        return skill

    @classmethod
    async def get_by_name(cls, name):
        return cls.rows.get(name)

    @classmethod
    async def get_by_display_name(cls, display_name):
        return next((s for s in cls.rows.values() if s.display_name == display_name), None)

    @classmethod
    async def get_page(cls, keyword=None, enabled=None, page=1, page_size=10):
        items = list(cls.rows.values())
        if keyword:
            items = [s for s in items if keyword in s.display_name or keyword in s.description]
        if enabled is not None:
            items = [s for s in items if bool(s.enabled) == enabled]
        return items[(page - 1) * page_size : page * page_size], len(items)

    @classmethod
    async def list_enabled(cls):
        return [s for s in cls.rows.values() if s.enabled]

    @classmethod
    async def set_enabled(cls, name, enabled):
        if name not in cls.rows:
            return False
        cls.rows[name].enabled = enabled
        return True

    @classmethod
    async def delete_by_name(cls, name):
        return cls.rows.pop(name, None) is not None


@pytest.fixture
def service(tmp_path, monkeypatch):
    FakeSkillDao.reset()
    monkeypatch.setattr(service_module, "LinsightSkillDao", FakeSkillDao)
    monkeypatch.setattr(service_module.PermissionService, "authorize", AsyncMock())
    return SkillService(store=SkillStore(root=tmp_path))


def _form(**overrides) -> SkillCreateForm:
    payload = {
        "display_name": "季度财报分析",
        "name": "ji-du-cai-bao-fen-xi",
        "description": "抽取核心指标并生成结构化报告。",
        "content": "# 季度财报分析\n\n1. 第一步",
    }
    payload.update(overrides)
    return SkillCreateForm(**payload)


def _md_bytes(name="demo-skill", description="demo desc", display_name="演示技能") -> bytes:
    return (
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  display-name: {display_name}\n---\n\n# body\n"
    ).encode()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


class TestCreate:
    async def test_create_from_form(self, service):
        detail = await service.create_from_form(TENANT, USER, _form())
        assert detail.name == "ji-du-cai-bao-fen-xi"
        assert detail.display_name == "季度财报分析"
        assert detail.enabled is True
        assert detail.source == "manual"
        # SKILL.md rendered with display-name metadata
        text = service.store.read_text(TENANT, detail.name)
        assert "display-name: 季度财报分析" in text
        # owner tuple written best-effort
        service_module.PermissionService.authorize.assert_awaited_once()

    async def test_duplicate_name_rejected(self, service):
        await service.create_from_form(TENANT, USER, _form())
        with pytest.raises(SkillNameDuplicateError):
            await service.create_from_form(TENANT, USER, _form(display_name="另一个名字"))

    async def test_duplicate_display_name_rejected(self, service):
        await service.create_from_form(TENANT, USER, _form())
        with pytest.raises(SkillNameDuplicateError):
            await service.create_from_form(TENANT, USER, _form(name="ling-yi-ge"))

    @pytest.mark.parametrize("bad_name", ["Upper-Case", "中文名", "double--hyphen", "-lead"])
    async def test_illegal_skill_id_rejected(self, service, bad_name):
        with pytest.raises(SkillValidationError):
            await service.create_from_form(TENANT, USER, _form(name=bad_name))

    async def test_create_from_md_upload(self, service):
        detail = await service.create_from_upload(TENANT, USER, "demo-skill.md", _md_bytes())
        assert detail.name == "demo-skill"
        assert detail.display_name == "演示技能"
        assert [f.path for f in detail.files] == [SKILL_MD]

    async def test_create_from_zip_bundle(self, service):
        data = _zip_bytes({"demo-skill/SKILL.md": _md_bytes(), "demo-skill/scripts/a.py": b"print(1)"})
        detail = await service.create_from_upload(TENANT, USER, "demo-skill.skill", data)
        assert {f.path for f in detail.files} == {SKILL_MD, "scripts/a.py"}
        # bundle total size lands in the DB row (size is not part of SkillDetail)
        assert FakeSkillDao.rows["demo-skill"].size == sum(f.size for f in detail.files)

    async def test_zip_without_skill_md_rejected(self, service):
        with pytest.raises(SkillValidationError, match="SKILL.md"):
            await service.create_from_upload(TENANT, USER, "x.zip", _zip_bytes({"readme.md": b"x"}))

    async def test_oversize_rejected(self, service):
        with pytest.raises(SkillFileTooLargeError):
            await service.create_from_upload(TENANT, USER, "big.md", b"x" * (MAX_BUNDLE_SIZE + 1))

    async def test_unsupported_extension_rejected(self, service):
        with pytest.raises(SkillValidationError, match="unsupported"):
            await service.create_from_upload(TENANT, USER, "skill.tar.gz", b"x")

    async def test_missing_description_rejected(self, service):
        bad = b"---\nname: demo-skill\n---\n\nbody"
        with pytest.raises(SkillValidationError, match="description"):
            await service.create_from_upload(TENANT, USER, "demo-skill.md", bad)


class TestQueries:
    async def test_page_and_selectable(self, service):
        await service.create_from_form(TENANT, USER, _form())
        await service.create_from_form(
            TENANT, USER, _form(name="he-tong-shen-yue", display_name="合同审阅", description="审阅合同条款。")
        )
        await service.set_status("he-tong-shen-yue", False)

        page = await service.get_page(keyword=None, enabled=None, page=1, page_size=10)
        assert page.total == 2
        selectable = await service.get_selectable()
        assert [s.display_name for s in selectable] == ["季度财报分析"]

        filtered = await service.get_page(keyword="合同", enabled=None, page=1, page_size=10)
        assert filtered.total == 1

    async def test_detail_unknown_name_404(self, service):
        # built-in names also take this path: existence is not leaked.
        with pytest.raises(SkillNotFoundError):
            await service.get_detail(TENANT, "not-exist")

    async def test_read_bundle_file(self, service):
        data = _zip_bytes({"SKILL.md": _md_bytes(), "reference/a.md": b"# ref"})
        await service.create_from_upload(TENANT, USER, "demo-skill.zip", data)
        content = await service.read_bundle_file(TENANT, "demo-skill", "reference/a.md")
        assert content.content == "# ref"
        with pytest.raises(SkillNotFoundError):
            await service.read_bundle_file(TENANT, "demo-skill", "missing.md")
        with pytest.raises(SkillValidationError):
            await service.read_bundle_file(TENANT, "demo-skill", "../escape.md")


class TestUpdateDelete:
    async def test_update_form_keeps_assets(self, service):
        data = _zip_bytes({"SKILL.md": _md_bytes(), "scripts/a.py": b"print(1)"})
        await service.create_from_upload(TENANT, USER, "demo-skill.zip", data)
        detail = await service.update_from_form(
            TENANT,
            "demo-skill",
            _form(name="demo-skill", display_name="演示技能v2", description="新描述。", content="# 新正文"),
        )
        assert detail.display_name == "演示技能v2"
        assert {f.path for f in detail.files} == {SKILL_MD, "scripts/a.py"}
        assert "# 新正文" in service.store.read_text(TENANT, "demo-skill")

    async def test_update_form_cannot_change_id(self, service):
        await service.create_from_form(TENANT, USER, _form())
        with pytest.raises(SkillValidationError, match="cannot be changed"):
            await service.update_from_form(TENANT, "ji-du-cai-bao-fen-xi", _form(name="other-id"))

    async def test_update_upload_replaces_bundle(self, service):
        await service.create_from_upload(
            TENANT, USER, "demo-skill.zip", _zip_bytes({"SKILL.md": _md_bytes(), "old.txt": b"stale"})
        )
        detail = await service.update_from_upload(
            TENANT,
            "demo-skill",
            "demo-skill.zip",
            _zip_bytes({"SKILL.md": _md_bytes(display_name="演示技能v3"), "new.txt": b"fresh"}),
        )
        assert detail.display_name == "演示技能v3"
        assert {f.path for f in detail.files} == {SKILL_MD, "new.txt"}

    async def test_update_upload_name_mismatch_rejected(self, service):
        await service.create_from_upload(TENANT, USER, "demo-skill.md", _md_bytes())
        with pytest.raises(SkillValidationError, match="must equal"):
            await service.update_from_upload(
                TENANT, "demo-skill", "other.md", _md_bytes(name="other-name", display_name="别名")
            )

    async def test_set_status_unknown_404(self, service):
        with pytest.raises(SkillNotFoundError):
            await service.set_status("not-exist", True)

    async def test_delete_removes_db_and_disk(self, service):
        await service.create_from_form(TENANT, USER, _form())
        await service.delete(TENANT, "ji-du-cai-bao-fen-xi")
        assert not service.store.exists(TENANT, "ji-du-cai-bao-fen-xi")
        with pytest.raises(SkillNotFoundError):
            await service.get_detail(TENANT, "ji-du-cai-bao-fen-xi")

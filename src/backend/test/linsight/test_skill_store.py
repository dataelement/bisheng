"""F035 Track D — SkillStore / slugify / frontmatter / zip unit tests (TD-3)."""

import io
import zipfile

import pytest

from bisheng.linsight.domain.services.skill_store import (
    SKILL_MD,
    SkillStore,
    compose_skill_md,
    parse_skill_md,
    slugify_pinyin,
    unpack_zip_bytes,
    validate_skill_name,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


SKILL_MD_TEXT = (
    "---\nname: demo-skill\ndescription: demo description\nmetadata:\n  display-name: 演示技能\n---\n\n# Demo body\n"
)


class TestSlugifyPinyin:
    def test_chinese_to_pinyin(self):
        assert slugify_pinyin("标书撰写流程") == "biao-shu-zhuan-xie-liu-cheng"

    def test_mixed_ascii_kept(self):
        assert slugify_pinyin("客户投诉处理SOP") == "ke-hu-tou-su-chu-li-sop"

    def test_fullwidth_punctuation_collapses(self):
        assert slugify_pinyin("季度财报分析 v2.0（修订）") == "ji-du-cai-bao-fen-xi-v2-0-xiu-ding"

    def test_symbols_only_returns_empty(self):
        assert slugify_pinyin("！！！") == ""

    def test_length_cap_and_legal_shape(self):
        slug = slugify_pinyin("析" * 100)
        assert len(slug) <= 64
        assert validate_skill_name(slug) is None

    def test_no_leading_trailing_or_double_hyphen(self):
        slug = slugify_pinyin("  数据-周报  生成  ")
        assert "--" not in slug
        assert not slug.startswith("-") and not slug.endswith("-")


class TestValidateSkillName:
    @pytest.mark.parametrize("name", ["a", "demo-skill", "a1-b2-c3", "x" * 64])
    def test_legal(self, name):
        assert validate_skill_name(name) is None

    @pytest.mark.parametrize(
        "name", ["", "x" * 65, "Upper-Case", "中文名", "-lead", "trail-", "double--hyphen", "under_score", "dot.name"]
    )
    def test_illegal(self, name):
        assert validate_skill_name(name) is not None


class TestFrontmatter:
    def test_parse_roundtrip(self):
        meta, body = parse_skill_md(SKILL_MD_TEXT)
        assert meta["name"] == "demo-skill"
        assert meta["metadata"]["display-name"] == "演示技能"
        assert body.strip() == "# Demo body"

    def test_compose_then_parse(self):
        text = compose_skill_md(
            name="ji-du-cai-bao",
            description="季度财报分析",
            body="# 正文",
            display_name="季度财报分析",
            extra_metadata={"sop-id": "17"},
        )
        meta, body = parse_skill_md(text)
        assert meta["name"] == "ji-du-cai-bao"
        assert meta["metadata"]["display-name"] == "季度财报分析"
        assert meta["metadata"]["sop-id"] == "17"
        assert body.strip() == "# 正文"

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="frontmatter"):
            parse_skill_md("# no frontmatter here")

    def test_non_mapping_frontmatter_raises(self):
        with pytest.raises(ValueError, match="mapping"):
            parse_skill_md("---\n- just\n- a list\n---\nbody")


class TestUnpackZip:
    def test_flat_zip(self):
        files = unpack_zip_bytes(_zip_bytes({SKILL_MD: b"x", "scripts/run.py": b"y"}))
        assert set(files) == {SKILL_MD, "scripts/run.py"}

    def test_wrapper_dir_stripped(self):
        files = unpack_zip_bytes(_zip_bytes({"my-skill/SKILL.md": b"x", "my-skill/reference/a.md": b"y"}))
        assert set(files) == {SKILL_MD, "reference/a.md"}

    def test_junk_entries_filtered(self):
        files = unpack_zip_bytes(_zip_bytes({SKILL_MD: b"x", "__MACOSX/._SKILL.md": b"j", "sub/.DS_Store": b"j"}))
        assert set(files) == {SKILL_MD}

    def test_missing_skill_md_raises(self):
        with pytest.raises(ValueError, match="SKILL.md"):
            unpack_zip_bytes(_zip_bytes({"readme.md": b"x"}))

    def test_bad_zip_raises(self):
        with pytest.raises(ValueError, match="invalid zip"):
            unpack_zip_bytes(b"not a zip at all")


class TestSkillStore:
    @pytest.fixture
    def store(self, tmp_path):
        return SkillStore(root=tmp_path)

    def test_write_read_list_delete(self, store):
        size = store.write_bundle(1, "demo-skill", {SKILL_MD: SKILL_MD_TEXT.encode(), "scripts/a.py": b"print(1)"})
        assert size == len(SKILL_MD_TEXT.encode()) + len(b"print(1)")
        assert store.exists(1, "demo-skill")
        assert store.read_text(1, "demo-skill").startswith("---")
        files = store.list_files(1, "demo-skill")
        assert files[0]["path"] == SKILL_MD  # SKILL.md always first
        assert {f["path"] for f in files} == {SKILL_MD, "scripts/a.py"}
        assert store.object_path(1, "demo-skill") == "data/skills/1/demo-skill"
        assert store.delete(1, "demo-skill")
        assert not store.exists(1, "demo-skill")

    def test_overwrite_removes_stale_assets(self, store):
        store.write_bundle(1, "demo-skill", {SKILL_MD: b"v1", "old.txt": b"stale"})
        store.write_bundle(1, "demo-skill", {SKILL_MD: b"v2"})
        assert {f["path"] for f in store.list_files(1, "demo-skill")} == {SKILL_MD}
        assert store.read_text(1, "demo-skill") == "v2"

    def test_tenant_isolation_by_path(self, store):
        store.write_bundle(1, "demo-skill", {SKILL_MD: b"t1"})
        assert not store.exists(2, "demo-skill")
        assert store.list_files(2, "demo-skill") == []

    @pytest.mark.parametrize("evil", ["../evil.md", "/abs.md", "a/../../evil.md"])
    def test_traversal_rejected_on_write(self, store, evil):
        with pytest.raises(ValueError, match="illegal bundle path"):
            store.write_bundle(1, "demo-skill", {SKILL_MD: b"x", evil: b"boom"})

    def test_traversal_rejected_on_read(self, store):
        store.write_bundle(1, "demo-skill", {SKILL_MD: b"x"})
        with pytest.raises(ValueError, match="illegal bundle path"):
            store.read_text(1, "demo-skill", "../../../etc/passwd")

    def test_bundle_requires_skill_md(self, store):
        with pytest.raises(ValueError, match="SKILL.md"):
            store.write_bundle(1, "demo-skill", {"other.md": b"x"})

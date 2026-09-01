"""F035 Track D — SkillStore / slugify / frontmatter / zip unit tests (TD-3)."""

import io
import zipfile

import pytest

from bisheng.linsight.domain.services import skill_store as skill_store_module
from bisheng.linsight.domain.services.skill_store import (
    SKILL_MD,
    SkillStore,
    bundle_content_hash,
    compose_skill_md,
    pack_bundle_zip,
    parse_skill_md,
    slugify_pinyin,
    unpack_zip_bytes,
    validate_skill_name,
)
from test.linsight.fixtures.fake_minio import FakeMinioStorage


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
        return SkillStore(root=tmp_path, minio=FakeMinioStorage())

    def test_write_read_list_delete(self, store):
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: SKILL_MD_TEXT.encode(), "scripts/a.py": b"print(1)"})
        assert ref.size == len(SKILL_MD_TEXT.encode()) + len(b"print(1)")
        assert ref.object_key == f"linsight/skills/1/demo-skill/{ref.content_hash}.zip"
        assert store.exists(1, "demo-skill", ref.content_hash)
        assert store.read_text(1, "demo-skill", ref.content_hash).startswith("---")
        files = store.list_files(1, "demo-skill", ref.content_hash)
        assert files[0]["path"] == SKILL_MD  # SKILL.md always first
        assert {f["path"] for f in files} == {SKILL_MD, "scripts/a.py"}
        assert store.delete(1, "demo-skill")
        assert not store.exists(1, "demo-skill", ref.content_hash)

    def test_new_version_supersedes_without_touching_the_old_object(self, store):
        """Each write is its own object, so a concurrent reader of v1 keeps working."""
        v1 = store.write_bundle(1, "demo-skill", {SKILL_MD: b"v1", "old.txt": b"stale"})
        v2 = store.write_bundle(1, "demo-skill", {SKILL_MD: b"v2"})
        assert v1.content_hash != v2.content_hash
        assert {f["path"] for f in store.list_files(1, "demo-skill", v2.content_hash)} == {SKILL_MD}
        assert store.read_text(1, "demo-skill", v2.content_hash) == "v2"
        # v1 is superseded, not destroyed — pruning it in the writer would race
        # with a concurrent writer publishing its own version.
        assert store.read_text(1, "demo-skill", v1.content_hash) == "v1"

    def test_delete_removes_every_version(self, store):
        v1 = store.write_bundle(1, "demo-skill", {SKILL_MD: b"v1"})
        v2 = store.write_bundle(1, "demo-skill", {SKILL_MD: b"v2"})
        assert store.delete(1, "demo-skill")
        assert not store.exists(1, "demo-skill", v1.content_hash)
        assert not store.exists(1, "demo-skill", v2.content_hash)

    def test_tenant_isolation_by_key(self, store):
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: b"t1"})
        assert not store.exists(2, "demo-skill", ref.content_hash)
        assert store.list_files(2, "demo-skill", ref.content_hash) == []

    def test_cache_hit_does_no_network_io(self, store):
        """The cache directory IS the content hash, so a hit needs no probe at all."""
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: b"x"})
        store.minio.reset_counters()
        store.read_text(1, "demo-skill", ref.content_hash)
        store.list_files(1, "demo-skill", ref.content_hash)
        assert (store.minio.get_calls, store.minio.exists_calls) == (0, 0)

    def test_materializes_from_storage_when_cache_is_cold(self, store, tmp_path):
        """A worker that never saw the write still resolves the bundle."""
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: b"x", "scripts/a.py": b"print(1)"})
        cold = SkillStore(root=tmp_path / "other-node", minio=store.minio)
        assert cold.read_bytes(1, "demo-skill", ref.content_hash, "scripts/a.py") == b"print(1)"

    def test_missing_object_raises_not_found(self, store):
        with pytest.raises(FileNotFoundError):
            store.read_text(1, "demo-skill", "0" * 64)

    @pytest.mark.parametrize("evil", ["../evil.md", "/abs.md", "a/../../evil.md"])
    def test_traversal_rejected_on_write(self, store, evil):
        with pytest.raises(ValueError, match="illegal bundle path"):
            store.write_bundle(1, "demo-skill", {SKILL_MD: b"x", evil: b"boom"})

    def test_traversal_rejected_on_read(self, store):
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: b"x"})
        with pytest.raises(ValueError, match="illegal bundle path"):
            store.read_text(1, "demo-skill", ref.content_hash, "../../../etc/passwd")

    def test_materializing_a_tampered_object_cannot_escape_the_cache_dir(self, store, tmp_path):
        """Materialization is a second write-to-disk path and must re-check paths.

        The upload path's guards live in skill_service/_parse_upload and in
        write_bundle; neither runs when bytes come back from storage.
        """
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: b"x"})
        # Hand-crafted archive whose entry escapes — pack_bundle_zip would refuse
        # to produce this, so it can only arrive from a corrupted/tampered object.
        tampered = _zip_bytes({SKILL_MD: b"x", "../escaped.txt": b"boom"})
        store.minio.store[(store.minio.bucket, ref.object_key)] = tampered
        cold = SkillStore(root=tmp_path / "cold", minio=store.minio)
        with pytest.raises(ValueError, match="illegal bundle path"):
            cold.read_text(1, "demo-skill", ref.content_hash)
        assert not (tmp_path / "escaped.txt").exists()

    def test_materializing_an_oversized_object_is_refused(self, store, tmp_path, monkeypatch):
        ref = store.write_bundle(1, "demo-skill", {SKILL_MD: b"x"})
        monkeypatch.setattr(skill_store_module, "MAX_UNPACKED_SIZE", 4)
        store.minio.store[(store.minio.bucket, ref.object_key)] = _zip_bytes({SKILL_MD: b"0123456789"})
        cold = SkillStore(root=tmp_path / "cold2", minio=store.minio)
        with pytest.raises(ValueError, match="exceeds"):
            cold.read_text(1, "demo-skill", ref.content_hash)

    def test_bundle_requires_skill_md(self, store):
        with pytest.raises(ValueError, match="SKILL.md"):
            store.write_bundle(1, "demo-skill", {"other.md": b"x"})


class TestBundleContentHash:
    """Bundle identity must depend on content only — never on packing incidentals.

    This is the guard for a bug that would otherwise be invisible: if identity
    tracked the packed archive's bytes, the built-in seeder would judge every
    bundle "changed" on every startup and rewrite all tenants' copies forever.
    """

    BUNDLE = {
        SKILL_MD: b"---\nname: demo-skill\ndescription: d\n---\n\nbody",
        "scripts/run.py": b"print(1)\n",
        "references/guide.md": b"# guide\n",
    }

    def test_insertion_order_does_not_change_hash(self):
        shuffled = dict(reversed(list(self.BUNDLE.items())))
        assert bundle_content_hash(self.BUNDLE) == bundle_content_hash(shuffled)

    def test_content_change_changes_hash(self):
        changed = dict(self.BUNDLE, **{"scripts/run.py": b"print(2)\n"})
        assert bundle_content_hash(self.BUNDLE) != bundle_content_hash(changed)

    def test_renaming_a_file_changes_hash(self):
        renamed = {k: v for k, v in self.BUNDLE.items() if k != "scripts/run.py"}
        renamed["scripts/main.py"] = self.BUNDLE["scripts/run.py"]
        assert bundle_content_hash(self.BUNDLE) != bundle_content_hash(renamed)

    def test_path_and_content_boundary_is_unambiguous(self):
        """Concatenating path+content without a separator would collide these two."""
        a = {SKILL_MD: b"x", "ab": b"c"}
        b = {SKILL_MD: b"x", "a": b"bc"}
        assert bundle_content_hash(a) != bundle_content_hash(b)


class TestPackBundleZip:
    def test_packing_is_reproducible(self):
        """Same mapping, different insertion order and different wall-clock -> same bytes."""
        bundle = {SKILL_MD: b"x", "scripts/a.py": b"a", "b.txt": b"b"}
        shuffled = dict(reversed(list(bundle.items())))
        assert pack_bundle_zip(bundle) == pack_bundle_zip(shuffled)

    def test_roundtrips_through_the_unpacker(self):
        bundle = {SKILL_MD: b"x", "assets/logo.png": b"\x89PNG\r\n\x1a\n\xff\xfe"}
        assert unpack_zip_bytes(pack_bundle_zip(bundle)) == bundle

    @pytest.mark.parametrize("evil", ["../evil.md", "/abs.md"])
    def test_traversal_rejected_when_packing(self, evil):
        with pytest.raises(ValueError, match="illegal bundle path"):
            pack_bundle_zip({SKILL_MD: b"x", evil: b"boom"})

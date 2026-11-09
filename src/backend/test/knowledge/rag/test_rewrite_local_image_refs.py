"""Plain-text docx leaves no media directory; rewriting image refs must not listdir it."""

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


def _loader(tmp_path, media: str) -> BaseBishengLoader:
    loader = BaseBishengLoader(
        file_path="plain.docx",
        file_metadata={},
        file_extension="docx",
        tmp_dir=str(tmp_path),
        image_object_dir="kb/images",
        image_url_builder=lambda name: f"/bucket/kb/images/{name}",
    )
    loader.local_image_dir = media
    return loader


def test_missing_media_dir_keeps_plain_text(tmp_path):
    media = str(tmp_path / "doc-id" / "media")
    content = "纯文字段落，没有图片。"

    assert _loader(tmp_path, media).rewrite_local_image_refs(content) == content


def test_existing_media_dir_rewrites_local_paths(tmp_path):
    media_dir = tmp_path / "doc-id" / "media"
    media_dir.mkdir(parents=True)
    (media_dir / "image1.png").write_bytes(b"png")
    local_ref = str(media_dir / "image1.png")

    rewritten = _loader(tmp_path, str(media_dir)).rewrite_local_image_refs(f"见图 {local_ref}")

    assert rewritten == "见图 /bucket/kb/images/image1.png"

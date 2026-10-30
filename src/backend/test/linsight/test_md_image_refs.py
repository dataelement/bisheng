"""Markdown deliverable images: path resolution, data-URI inlining and the zip bundle."""

import io
import zipfile
from types import SimpleNamespace

import pytest

from bisheng.linsight.domain.services import md_image_refs
from bisheng.linsight.domain.services.deliverable_download_service import (
    deliverable_workspace_path,
    find_deliverable,
)

PNG = b"\x89PNG-fake"


def _fetcher(files: dict[str, bytes], seen: list[list[str]] | None = None):
    async def _fetch(paths):
        if seen is not None:
            seen.append(list(paths))
        return {p: files[p] for p in paths if p in files}

    return _fetch


def test_candidates_try_md_dir_then_workspace_root():
    assert md_image_refs.image_path_candidates("charts/a.png", "output/r.md") == [
        "output/charts/a.png",
        "charts/a.png",
    ]
    assert md_image_refs.image_path_candidates("/output/a.png", "output/r.md") == ["output/a.png"]
    assert md_image_refs.image_path_candidates("../../x.png", "output/r.md") == []


def test_has_local_image_refs_ignores_remote_and_inline():
    assert md_image_refs.has_local_image_refs("![a](charts/a.png)")
    assert md_image_refs.has_local_image_refs('<img src="a.png">')
    assert not md_image_refs.has_local_image_refs("![a](https://x/a.png) ![b](data:image/png;base64,AA==)")
    assert not md_image_refs.has_local_image_refs("plain [link](a.md)")


async def test_non_image_candidates_are_never_fetched():
    seen: list[list[str]] = []
    found, missing = await md_image_refs.resolve_local_images("![a](notes.txt)", "output/r.md", _fetcher({}, seen))
    assert found == {} and missing == ["notes.txt"] and seen == []


async def test_bundle_rewrites_paths_and_packs_images():
    md = (
        "# R\n\n![曲线](output/charts/curve.png)\n\n![宏量](charts/macros.png)\n\n"
        "![同一张](/output/charts/curve.png)\n\n![别处同名](scratch/macros.png)\n\n![丢了](charts/gone.png)\n"
    )
    files = {
        "output/charts/curve.png": PNG + b"1",
        "output/charts/macros.png": PNG + b"2",
        "scratch/macros.png": PNG + b"3",
    }
    data = await md_image_refs.build_markdown_bundle(md, "减肥计划.md", "output/减肥计划.md", _fetcher(files))

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        out_md = zf.read("减肥计划.md").decode()
        assert names == {"减肥计划.md", "images/curve.png", "images/macros.png", "images/macros-2.png"}
        assert zf.read("images/curve.png") == PNG + b"1"
        assert {zf.read("images/macros.png"), zf.read("images/macros-2.png")} == {PNG + b"2", PNG + b"3"}
    # Both spellings of the same file point at one entry; the missing one is untouched.
    assert out_md.count("](images/curve.png)") == 2
    assert "](charts/gone.png)" in out_md
    assert "output/charts" not in out_md


async def test_bundle_is_none_when_no_image_resolves():
    assert await md_image_refs.build_markdown_bundle("![a](a.png)", "r.md", "output/r.md", _fetcher({})) is None
    assert await md_image_refs.build_markdown_bundle("text", "r.md", "output/r.md", _fetcher({})) is None


async def test_inline_local_images_uses_data_uri_and_reports_missing():
    md, missing = await md_image_refs.inline_local_images(
        '![a](charts/a.png) <img src="b.png">', "output/r.md", _fetcher({"output/charts/a.png": PNG})
    )
    assert "](data:image/png;base64," in md
    assert '<img src="b.png">' in md and missing == ["b.png"]


def _version(final_files):
    return SimpleNamespace(id="48e1bcaeae7f4d6fa3dc5d2c72c346e1", output_result={"final_files": final_files})


def test_deliverable_workspace_path_from_recorded_local_path():
    v = _version([])
    info = {"file_path": "/root/.cache/bisheng/linsight/48e1bcae/output/减肥计划.md"}
    assert deliverable_workspace_path(v, info) == "output/减肥计划.md"
    assert deliverable_workspace_path(v, {"rel_path": "output/x.md", "file_path": ""}) == "output/x.md"
    assert deliverable_workspace_path(v, {"file_path": "/elsewhere/x.md"}) is None


def test_find_deliverable_matches_only_this_versions_final_files():
    key = "linsight/final_result/48e1bcaeae7f4d6fa3dc5d2c72c346e1/675a3970.md"
    v = _version([{"file_url": key, "file_name": "减肥计划.md"}, "garbage"])
    assert find_deliverable(v, key, "bisheng")["file_name"] == "减肥计划.md"
    assert find_deliverable(v, "linsight/final_result/48e1bcaeae7f4d6fa3dc5d2c72c346e1/other.md", "bisheng") is None


# --- endpoints: md bundle download and image-embedding pdf/docx conversion ----

SVID = "48e1bcaeae7f4d6fa3dc5d2c72c346e1"
MD_KEY = f"linsight/final_result/{SVID}/675a3970.md"
REPORT_MD = "# 计划\n\n![曲线](output/charts/curve.png)\n"


@pytest.fixture
def stored_task(monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.citation.domain.services import citation_export_service
    from bisheng.linsight.api.endpoints import linsight as endpoint

    version = SimpleNamespace(
        id=SVID,
        session_id="fee0fcde",
        output_result={
            "final_files": [
                {
                    "file_url": MD_KEY,
                    "file_name": "减肥计划.md",
                    "file_path": f"/root/.cache/bisheng/linsight/{SVID[:8]}/output/减肥计划.md",
                }
            ]
        },
    )
    monkeypatch.setattr(citation_export_service, "resolve_items_for_export", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        endpoint.LinsightArtifactPreviewService, "load_accessible_version", AsyncMock(return_value=version)
    )
    monkeypatch.setattr(endpoint, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(bucket="bisheng")))
    monkeypatch.setattr(
        endpoint.LinsightWorkbenchImpl,
        "download_file",
        AsyncMock(return_value=("减肥计划.md", REPORT_MD.encode("utf-8"))),
    )
    workspace = {"output/charts/curve.png": PNG}
    monkeypatch.setattr(endpoint, "workspace_fetcher", lambda svid: _fetcher(workspace))
    return endpoint, workspace


async def _body(resp) -> bytes:
    return b"".join([chunk async for chunk in resp.body_iterator])


async def test_md_bundle_endpoint_returns_zip_with_images(stored_task):
    endpoint, _ = stored_task
    resp = await endpoint.download_md_bundle(
        session_version_id=SVID,
        file_url=MD_KEY,
        file_name="减肥计划.md",
        login_user=SimpleNamespace(user_id=1),
        share_link=None,
    )
    assert resp.media_type == "application/zip"
    assert "%E5%87%8F%E8%82%A5%E8%AE%A1%E5%88%92.zip" in resp.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(await _body(resp))) as zf:
        assert zf.read("images/curve.png") == PNG
        assert "](images/curve.png)" in zf.read("减肥计划.md").decode()


async def test_md_bundle_endpoint_falls_back_to_plain_md_without_images(stored_task):
    endpoint, workspace = stored_task
    workspace.clear()
    resp = await endpoint.download_md_bundle(
        session_version_id=SVID,
        file_url=MD_KEY,
        file_name="减肥计划.md",
        login_user=SimpleNamespace(user_id=1),
        share_link=None,
    )
    assert resp.media_type.startswith("text/markdown")
    assert (await _body(resp)).decode() == REPORT_MD


async def test_md_bundle_endpoint_rejects_non_deliverable(stored_task):
    from bisheng.common.errcode.http_error import NotFoundError

    endpoint, _ = stored_task
    with pytest.raises(NotFoundError):
        await endpoint.download_md_bundle(
            session_version_id=SVID,
            file_url=f"linsight/session_files/{SVID}/scratch.md",
            file_name="x.md",
            login_user=SimpleNamespace(user_id=1),
            share_link=None,
        )


async def test_docx_conversion_embeds_workspace_images_when_version_given(stored_task, monkeypatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod
    from bisheng.linsight.domain.schemas.linsight_schema import DownloadFilesSchema

    endpoint, _ = stored_task
    seen = {}

    class _FakeMarkDocx:
        def __call__(self, md):
            seen["md"] = md
            return (b"DOCX", "t")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)
    await endpoint.download_md_to_pdf_or_docx(
        file_info=DownloadFilesSchema(file_name="减肥计划.md", file_url=MD_KEY),
        to_type="docx",
        session_version_id=SVID,
        login_user=SimpleNamespace(user_id=1),
        share_link=None,
    )
    assert "](data:image/png;base64," in seen["md"]

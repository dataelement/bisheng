"""F078 T13: decide which files a run delivers and store them as chat attachments."""

import os

import pytest

from bisheng.agent_runtime.domain.services.deliverables import DeliverableTarget, acollect_deliverables
from bisheng.linsight.domain.utils import snapshot_file_fingerprints
from test.linsight.fixtures.fake_minio import FakeMinioStorage

PPTX_MAGIC = b"PK\x03\x04rest-of-zip"


class _PathMinio(FakeMinioStorage):
    """The real client accepts a file path; the shared fake only takes bytes."""

    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        if isinstance(file, str):
            with open(file, "rb") as f:
                file = f.read()
        self.put_object_sync(bucket_name=bucket_name, object_name=object_name, file=file)


def _write(root, rel, data=b"x"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.fixture
def minio():
    return _PathMinio()


def _target(temp=False):
    return DeliverableTarget(
        object_dir="agent_runtime/tmp-t1" if temp else "chat/7/agent/c1",
        use_tmp_bucket=temp,
        url_for=lambda file_id: f"/api/v1/agent-runtime/files/c1/{file_id}",
    )


async def _collect(minio, file_dir, baseline, temp=False):
    return await acollect_deliverables(minio, file_dir, baseline, _target(temp))


class TestSelection:
    async def test_output_zone_wins(self, minio, tmp_path):
        root = str(tmp_path)
        _write(root, "skills/docx/SKILL.md")
        _write(root, "uploads/in.xlsx")
        baseline = snapshot_file_fingerprints(root)
        _write(root, "output/report.docx", PPTX_MAGIC)
        _write(root, "notes.txt")
        files = await _collect(minio, root, baseline)
        assert [f["file_name"] for f in files] == ["report.docx"]

    async def test_falls_back_to_new_files_elsewhere_when_output_is_empty(self, minio, tmp_path):
        root = str(tmp_path)
        baseline = snapshot_file_fingerprints(root)
        _write(root, "report.md", b"# hi")
        _write(root, "scratch/tmp.md")
        files = await _collect(minio, root, baseline)
        assert [f["file_name"] for f in files] == ["report.md"]

    async def test_unchanged_leftovers_are_not_delivered_again(self, minio, tmp_path):
        root = str(tmp_path)
        _write(root, "output/old.md", b"old")
        baseline = snapshot_file_fingerprints(root)
        assert await _collect(minio, root, baseline) == []

    async def test_modified_input_original_is_not_delivered(self, minio, tmp_path):
        root = str(tmp_path)
        _write(root, "uploads/in.xlsx", b"v1")
        baseline = snapshot_file_fingerprints(root)
        _write(root, "uploads/in.xlsx", b"v2")
        assert await _collect(minio, root, baseline) == []

    async def test_no_files_means_no_deliverables(self, minio, tmp_path):
        assert await _collect(minio, str(tmp_path), {}) == []


class TestFormatCheck:
    async def test_bad_office_file_is_kept_and_flagged(self, minio, tmp_path):
        root = str(tmp_path)
        baseline = snapshot_file_fingerprints(root)
        _write(root, "output/deck.pptx", b"this is plain text")
        files = await _collect(minio, root, baseline)
        assert len(files) == 1
        assert files[0]["file_name"] == "deck.pptx"
        assert files[0]["format_error"]

    async def test_good_office_file_has_no_flag(self, minio, tmp_path):
        root = str(tmp_path)
        baseline = snapshot_file_fingerprints(root)
        _write(root, "output/deck.pptx", PPTX_MAGIC)
        files = await _collect(minio, root, baseline)
        assert "format_error" not in files[0]


class TestStorage:
    async def test_formal_session_files_go_to_the_public_bucket(self, minio, tmp_path):
        root = str(tmp_path)
        baseline = snapshot_file_fingerprints(root)
        _write(root, "output/周报.docx", PPTX_MAGIC)
        (file,) = await _collect(minio, root, baseline)
        assert file["object_name"].startswith("chat/7/agent/c1/")
        assert file["object_name"].endswith(".docx")
        # ASCII-only object key: the display name stays in file_name.
        assert file["object_name"].isascii()
        assert (minio.bucket, file["object_name"]) in minio.store
        assert file["file_url"] == f"/api/v1/agent-runtime/files/c1/{file['file_id']}"
        assert file["size"] == len(PPTX_MAGIC)

    async def test_temp_session_files_go_to_the_tmp_bucket(self, minio, tmp_path):
        root = str(tmp_path)
        baseline = snapshot_file_fingerprints(root)
        _write(root, "output/a.md", b"a")
        (file,) = await _collect(minio, root, baseline, temp=True)
        assert (minio.tmp_bucket, file["object_name"]) in minio.store
        assert file["bucket"] == "tmp"

    async def test_file_ids_are_unique(self, minio, tmp_path):
        root = str(tmp_path)
        baseline = snapshot_file_fingerprints(root)
        for i in range(5):
            _write(root, f"output/f{i}.md", b"x")
        files = await _collect(minio, root, baseline)
        assert len({f["file_id"] for f in files}) == 5

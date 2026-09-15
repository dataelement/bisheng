"""MinIO 对象键重写与任务合并."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.minio_keys import (
    collect_map_jobs,
    extract_object_key,
    merge_jobs_tsv,
    rewrite_object_key,
    rewrite_stored_value,
)


def test_rewrite_object_key_keeps_prefix():
    assert rewrite_object_key("original/12.pdf", "90") == "original/90.pdf"


def test_extract_object_key_from_url():
    assert extract_object_key("https://minio.local/bisheng/tmp/a.png?X-Amz=1") == "tmp/a.png"


def test_rewrite_stored_files_json():
    new, jobs = rewrite_stored_value(
        [{"filepath": "chat/12.png", "name": "a.png"}],
        "50",
        ref="12",
        kind="files",
    )
    assert new[0]["filepath"] == "chat/50.png"
    assert jobs[0]["src"] == "chat/12.png"
    assert jobs[0]["dst"] == "chat/50.png"


def test_collect_and_merge_jobs(tmp_path: Path):
    rows = [
        {
            "b_id": "12",
            "src_object_key": "original/12.pdf",
            "dst_object_key": "original/20.pdf",
            "extra_jobs": [
                {
                    "b_file_id": "12",
                    "src": "thumbnails/a.jpg",
                    "dst": "thumbnails/20.jpg",
                    "kind": "thumbnails",
                }
            ],
        }
    ]
    jobs = collect_map_jobs(rows)
    assert {j["dst"] for j in jobs} == {"original/20.pdf", "thumbnails/20.jpg"}
    path = tmp_path / "minio-jobs.tsv"
    merge_jobs_tsv(path, jobs, set())
    again = merge_jobs_tsv(path, jobs, set())
    assert len(again) == 2

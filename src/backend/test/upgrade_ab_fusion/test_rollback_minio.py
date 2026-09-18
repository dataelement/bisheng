"""回滚 MinIO 名单: 只收本批 dst, src==dst 和 A 原键不删."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.rollback_minio import collect_rollback_minio_keys, is_rollback_minio_key


def _keys(rows: list[dict]) -> set[str]:
    return {r["key"] for r in rows}


def test_jobs_dst_collected_src_equal_dst_skipped():
    rows = collect_rollback_minio_keys(
        jobs=[
            {"src": "original/12.pdf", "dst": "original/90.pdf"},
            {"src": "icon/keep.png", "dst": "icon/keep.png"},
            {"src": "original/13.pdf", "dst": "."},
        ]
    )
    assert _keys(rows) == {"original/90.pdf"}


def test_fusion_map_file_note_parsed_and_bind_skipped():
    rows = collect_rollback_minio_keys(
        fusion_maps=[
            {
                "entity": "file",
                "action": "create",
                "note": "original/94349.docx|original/253.xlsx",
            },
            {
                "entity": "file",
                "action": "bind",
                "note": "original/1.pdf|original/1.pdf",
            },
            {
                "entity": "knowledge",
                "action": "create",
                "note": "original/should-not.pdf|original/x.pdf",
            },
        ]
    )
    assert _keys(rows) == {"original/94349.docx"}


def test_reconstruct_from_file_map():
    rows = collect_rollback_minio_keys(
        files=[{"id": "12", "object_name": "original/12.pdf"}],
        file_map={"12": "90"},
    )
    assert _keys(rows) == {"original/90.pdf"}
    assert rows[0]["src"] == "original/12.pdf"


def test_forbid_and_dot_rejected():
    assert is_rollback_minio_key("original/90.pdf")
    assert not is_rollback_minio_key(".")
    assert not is_rollback_minio_key("./x")
    rows = collect_rollback_minio_keys(
        jobs=[{"src": "a.png", "dst": "icon/new.png"}],
        forbid={"icon/new.png"},
    )
    assert _keys(rows) == set()


def test_bind_file_id_not_deleted_even_if_job_lists_it():
    rows = collect_rollback_minio_keys(
        jobs=[
            {"src": "original/12.pdf", "dst": "original/1.pdf"},
            {"src": "original/13.pdf", "dst": "original/94349.pdf"},
        ],
        fusion_maps=[
            {"entity": "file", "action": "bind", "dst_id": "1"},
            {
                "entity": "file",
                "action": "create",
                "dst_id": "94349",
                "note": "original/94349.pdf|original/13.pdf",
            },
        ],
    )
    assert _keys(rows) == {"original/94349.pdf"}


def test_file_map_rows_skip_bind_action():
    rows = collect_rollback_minio_keys(
        files=[
            {"id": "12", "object_name": "original/12.pdf"},
            {"id": "13", "object_name": "original/13.pdf"},
        ],
        file_map_rows=[
            {"b_id": "12", "a_id": "1", "action": "bind"},
            {"b_id": "13", "a_id": "90", "action": "create"},
        ],
    )
    assert _keys(rows) == {"original/90.pdf"}


def test_union_dedup_jobs_over_reconstruct():
    rows = collect_rollback_minio_keys(
        jobs=[
            {"src": "original/12.pdf", "dst": "original/90.pdf"},
            {"src": "partitions/12.json", "dst": "partitions/90.json"},
        ],
        files=[{"id": "12", "object_name": "original/12.pdf"}],
        file_map={"12": "90"},
    )
    assert _keys(rows) == {"original/90.pdf", "partitions/90.json"}
    sources = {r["key"]: r["source"] for r in rows}
    assert sources["original/90.pdf"] == "minio_jobs"
    assert sources["partitions/90.json"] == "minio_jobs"


def test_cli_loads_file_map_csv(tmp_path):
    from fusion.rollback_minio import main as rollback_minio_main

    file_map = tmp_path / "file-map.csv"
    file_map.write_text("b_id,a_id,action\n13,90,create\n12,1,bind\n", encoding="utf-8")
    files = tmp_path / "b-files.tsv"
    files.write_text(
        "id\tobject_name\n13\toriginal/13.pdf\n12\toriginal/12.pdf\n",
        encoding="utf-8",
    )
    out = tmp_path / "keys.tsv"
    import sys

    old = sys.argv
    sys.argv = [
        "rollback_minio.py",
        "--out",
        str(out),
        "--file-map",
        str(file_map),
        "--b-files",
        str(files),
    ]
    try:
        assert rollback_minio_main() == 0
    finally:
        sys.argv = old
    text = out.read_text(encoding="utf-8")
    assert "original/90.pdf" in text
    assert "original/1.pdf" not in text

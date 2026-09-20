"""回滚要删的 A MinIO 对象键. 只收本批拷过去的 dst, 不连库.

来源:
- minio-jobs.tsv 的 dst
- fusion_map note (file 行: dst_key|src_key)
- file-map + B 文件导出, 按同一套 original/{id}.ext 规则还原

不进名单:
- src 与 dst 相同 (可能是 A 上原来就有的键)
- forbid
- 空键 / . / ./
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
if str(PACK) not in sys.path:
    sys.path.insert(0, str(PACK))

from fusion.maps import SKIP_ROLLBACK_ACTIONS
from fusion.minio_keys import jobs_from_exported_files
from fusion.sql import load_csv, load_table, write_csv

FIELDS = ["key", "src", "source"]
BAD_KEYS = frozenset({".", "./", "/", ".."})


def is_rollback_minio_key(key: str) -> bool:
    """可当作 MinIO 对象名删除的键. 排除 mc 无法识别的当前目录项."""
    text = (key or "").strip()
    if not text or text in BAD_KEYS:
        return False
    if text.startswith("/") or text.startswith("."):
        return False
    return True


def _add(
    rows: list[dict[str, str]],
    seen: set[str],
    *,
    key: str,
    src: str = "",
    source: str = "",
    forbid: set[str],
    protected_stems: set[str],
) -> None:
    text = (key or "").strip()
    src_text = (src or "").strip()
    if not is_rollback_minio_key(text):
        return
    if text in forbid:
        return
    if _key_stem(text) in protected_stems:
        return
    if src_text and src_text == text:
        return
    if text in seen:
        return
    seen.add(text)
    rows.append({"key": text, "src": src_text, "source": source})


def _note_dst(note: str) -> tuple[str, str]:
    """file 行 note 为 dst|src. 解析不出则空."""
    text = (note or "").strip()
    if "|" not in text:
        return "", ""
    dst, src = text.split("|", 1)
    return dst.strip(), src.strip()


def _key_stem(key: str) -> str:
    name = key.rsplit("/", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _protected_file_stems(fusion_maps: list[dict] | None) -> set[str]:
    """bind/dedupe 的 dst 是 A 原 knowledgefile id, 对应对象键禁删."""
    stems: set[str] = set()
    for row in fusion_maps or []:
        if (row.get("entity") or "").strip() != "file":
            continue
        if (row.get("action") or "").strip() not in SKIP_ROLLBACK_ACTIONS:
            continue
        dst = str(row.get("dst_id") or row.get("a_id") or "").strip()
        if dst:
            stems.add(dst)
    return stems


def _create_file_map(
    file_map: dict[str, str] | None, file_map_rows: list[dict] | None
) -> dict[str, str]:
    if file_map_rows is not None:
        out: dict[str, str] = {}
        for row in file_map_rows:
            action = (row.get("action") or "create").strip()
            if action in SKIP_ROLLBACK_ACTIONS:
                continue
            src = str(row.get("b_id") or "").strip()
            dst = str(row.get("a_id") or "").strip()
            if src and dst:
                out[src] = dst
        return out
    return dict(file_map or {})


def collect_rollback_minio_keys(
    *,
    jobs: list[dict] | None = None,
    fusion_maps: list[dict] | None = None,
    files: list[dict] | None = None,
    file_map: dict[str, str] | None = None,
    file_map_rows: list[dict] | None = None,
    forbid: set[str] | None = None,
) -> list[dict[str, str]]:
    """去重后的 A 侧删除名单. 只含本批 dst."""
    blocked = {str(x).strip() for x in (forbid or set()) if str(x).strip()}
    protected = _protected_file_stems(fusion_maps)
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in jobs or []:
        _add(
            out,
            seen,
            key=str(row.get("dst") or row.get("key") or ""),
            src=str(row.get("src") or ""),
            source="minio_jobs",
            forbid=blocked,
            protected_stems=protected,
        )

    for row in fusion_maps or []:
        if (row.get("entity") or "").strip() != "file":
            continue
        if (row.get("action") or "").strip() in SKIP_ROLLBACK_ACTIONS:
            continue
        dst, src = _note_dst(str(row.get("note") or ""))
        _add(
            out,
            seen,
            key=dst,
            src=src,
            source="fusion_map",
            forbid=blocked,
            protected_stems=protected,
        )

    reconstructed = jobs_from_exported_files(
        files or [], _create_file_map(file_map, file_map_rows)
    )
    for row in reconstructed:
        _add(
            out,
            seen,
            key=str(row.get("dst") or ""),
            src=str(row.get("src") or ""),
            source="reconstruct",
            forbid=blocked,
            protected_stems=protected,
        )

    return out


def write_rollback_minio_keys(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv(path, FIELDS, rows, delimiter="\t")


def _load_optional(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    return load_table(path)


def _forbid_from(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    return {
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    }


def _files_from(b_files: Path | None, dump: Path | None) -> list[dict]:
    rows = _load_optional(b_files)
    if rows:
        return rows
    if dump is None or not dump.exists():
        return []
    payload = json.loads(dump.read_text(encoding="utf-8"))
    return list(payload.get("files") or [])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--jobs", default="")
    p.add_argument("--rollback-map", default="")
    p.add_argument("--file-map", default="")
    p.add_argument("--b-files", default="")
    p.add_argument("--dump", default="")
    p.add_argument("--forbid", default="")
    args = p.parse_args()
    file_map_rows: list[dict[str, str]] | None = None
    if args.file_map:
        fp = Path(args.file_map)
        if fp.exists():
            file_map_rows = load_csv(fp)
    rows = collect_rollback_minio_keys(
        jobs=_load_optional(Path(args.jobs) if args.jobs else None),
        fusion_maps=_load_optional(
            Path(args.rollback_map) if args.rollback_map else None
        ),
        files=_files_from(
            Path(args.b_files) if args.b_files else None,
            Path(args.dump) if args.dump else None,
        ),
        file_map_rows=file_map_rows,
        forbid=_forbid_from(Path(args.forbid) if args.forbid else None),
    )
    write_rollback_minio_keys(Path(args.out), rows)
    print(f"rollback minio keys={len(rows)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

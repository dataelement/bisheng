"""MinIO 拷贝任务: B 对象键 -> A 新键. 不覆盖 A 已有键."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from fusion.sql import load_table, write_csv

PATH_KEYS = frozenset(
    {
        "bbox_object_name",
        "file_url",
        "filepath",
        "flow_logo",
        "key",
        "logo",
        "object_name",
        "path",
        "preview_file_object_name",
        "template_name",
        "thumbnails",
        "url",
    }
)


def rewrite_object_key(old_key: str | None, new_file_id: str) -> str | None:
    """original/123.pdf -> original/{new_id}.pdf; 其它前缀同样替换末段文件名."""
    if not old_key:
        return old_key
    if "/" in old_key:
        prefix, rest = old_key.rsplit("/", 1)
        if "." in rest:
            _, ext = rest.rsplit(".", 1)
            return f"{prefix}/{new_file_id}.{ext}"
        return f"{prefix}/{new_file_id}"
    return old_key


def extract_object_key(value: str | None) -> str | None:
    """从对象键或签名 URL 里取出 MinIO object name. 认不出则返回 None."""
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("["):
        return None
    if text.startswith("http://") or text.startswith("https://"):
        path = unquote(urlparse(text).path).lstrip("/")
        if path.startswith("minio/"):
            path = path[len("minio/") :]
        parts = path.split("/", 1)
        if len(parts) == 2 and "." not in parts[0]:
            path = parts[1]
        return path or None
    if "://" in text:
        return None
    if "/" in text or "." in text:
        return text
    return None


def rewrite_stored_value(
    value,
    new_id: str,
    *,
    ref: str = "",
    kind: str = "",
) -> tuple:
    """重写字段里的对象键. 返回 (new_value, jobs)."""
    jobs: list[dict] = []

    def add_job(src: str, dst: str, job_kind: str) -> None:
        if not src or not dst:
            return
        jobs.append(
            {
                "b_file_id": ref,
                "src": src,
                "dst": dst,
                "kind": job_kind or kind or "object",
            }
        )

    def walk(node, parent_key: str = ""):
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, parent_key) for item in node]
        if isinstance(node, str) and parent_key in PATH_KEYS:
            src = extract_object_key(node)
            if not src:
                return node
            dst = rewrite_object_key(src, new_id)
            if dst:
                add_job(src, dst, parent_key)
                return dst
        return node

    if isinstance(value, (dict, list)):
        return walk(value), jobs
    if not isinstance(value, str):
        return value, jobs
    text = value.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return rewrite_stored_value(parsed, new_id, ref=ref, kind=kind)
    src = extract_object_key(value)
    if not src:
        return value, jobs
    dst = rewrite_object_key(src, new_id)
    if dst:
        add_job(src, dst, kind or "object")
        return dst, jobs
    return value, jobs


def _job_row(row: dict, src: str, dst: str, kind: str) -> dict:
    return {
        "b_file_id": row.get("b_id") or row.get("b_file_id") or "",
        "src": src,
        "dst": dst,
        "kind": kind,
    }


def collect_map_jobs(
    rows: list[dict], a_existing_keys: set[str] | None = None
) -> list[dict]:
    """从各域 map 行收集拷贝任务, 含 extra_jobs."""
    existing = a_existing_keys or set()
    jobs = list_file_jobs(rows, existing)
    seen = {(j["src"], j["dst"]) for j in jobs}
    for row in rows:
        for extra in row.get("extra_jobs") or []:
            src = extra.get("src") or ""
            dst = extra.get("dst") or ""
            if not src or not dst or (src, dst) in seen:
                continue
            if dst in existing:
                raise ValueError(f"MinIO 目标键与 A 冲突: {dst}")
            seen.add((src, dst))
            jobs.append(
                {
                    "b_file_id": extra.get("b_file_id") or row.get("b_id") or "",
                    "src": src,
                    "dst": dst,
                    "kind": extra.get("kind") or "extra",
                }
            )
    return jobs


def list_file_jobs(
    file_maps: list[dict], a_existing_keys: set[str] | None = None
) -> list[dict]:
    existing = a_existing_keys or set()
    jobs = []
    for row in file_maps:
        for src_k, dst_k in (
            ("src_object_key", "dst_object_key"),
            ("preview_src", "preview_dst"),
            ("bbox_src", "bbox_dst"),
            ("thumbnail_src", "thumbnail_dst"),
            ("logo_src", "logo_dst"),
        ):
            src = row.get(src_k) or ""
            dst = row.get(dst_k) or ""
            if not src or not dst:
                continue
            if dst in existing:
                raise ValueError(f"MinIO 目标键与 A 冲突: {dst}")
            jobs.append(_job_row(row, src, dst, src_k))
    return jobs


def merge_jobs_tsv(
    path: Path, new_jobs: list[dict], a_existing_keys: set[str] | None = None
) -> list[dict]:
    existing_keys = a_existing_keys or set()
    old = load_table(path) if path.exists() else []
    combined: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in list(old) + list(new_jobs):
        src = row.get("src") or ""
        dst = row.get("dst") or ""
        if not src or not dst or (src, dst) in seen:
            continue
        if dst in existing_keys:
            raise ValueError(f"MinIO 目标键与 A 冲突: {dst}")
        seen.add((src, dst))
        combined.append(
            {
                "b_file_id": row.get("b_file_id") or row.get("b_id") or "",
                "src": src,
                "dst": dst,
                "kind": row.get("kind") or "",
            }
        )
    write_jobs_tsv(path, combined)
    return combined


def write_jobs_tsv(path: Path, jobs: list[dict]) -> None:
    write_csv(path, ["b_file_id", "src", "dst", "kind"], jobs, delimiter="\t")

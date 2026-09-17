"""检索金标: 用同一向量在 B/A 对打, 比较重写后的 file_id. 不重新 Embedding."""

from __future__ import annotations


def hit_file_id(hit: dict) -> str:
    meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    for src in (hit, meta):
        for key in ("file_id", "document_id"):
            val = src.get(key)
            if val not in (None, ""):
                return str(val)
    return ""


def remap_ranked(hits: list[dict], file_map: dict[str, str]) -> list[str]:
    """B 命中按 file-map 换成 A 文件 ID. QA 占位等未映射 id 对成 0 (与 drop_field 一致)."""
    out: list[str] = []
    for hit in hits:
        src = hit_file_id(hit)
        if not src:
            continue
        dst = file_map.get(src)
        out.append(str(dst) if dst else "0")
    return out


def overlap_at_k(expected: list[str], actual: list[str], k: int) -> float:
    exp = [x for x in expected[:k] if x]
    act = set(actual[:k])
    if not exp:
        return 1.0
    return len([x for x in exp if x in act]) / len(exp)


def top1_match(expected: list[str], actual: list[str]) -> bool:
    if not expected or not actual:
        return False
    return expected[0] == actual[0]


def score_case(
    *,
    b_hits: list[dict],
    a_hits: list[dict],
    file_map: dict[str, str],
    k: int = 5,
    min_overlap: float = 0.8,
) -> dict:
    expected = remap_ranked(b_hits, file_map)
    actual = [hit_file_id(h) for h in a_hits if hit_file_id(h)]
    overlap = overlap_at_k(expected, actual, k)
    # convert 会重建 HNSW, top1 不稳定; 以 overlap@k 为硬门, top1 只记录
    ok = bool(expected) and overlap >= min_overlap
    return {
        "ok": ok,
        "expected": expected[:k],
        "actual": actual[:k],
        "overlap_at_k": overlap,
        "top1": top1_match(expected, actual),
        "reason": ""
        if ok
        else (
            "B 命中无法映射"
            if not expected
            else f"overlap@{k}={overlap:.2f} top1={expected[0] if expected else ''} vs {actual[0] if actual else ''}"
        ),
    }


def score_jobs(
    cases: list[dict],
    *,
    file_map: dict[str, str],
    k: int = 5,
    min_overlap: float = 0.8,
) -> dict:
    rows = []
    failed = 0
    for case in cases:
        scored = score_case(
            b_hits=case.get("b_hits") or [],
            a_hits=case.get("a_hits") or [],
            file_map=file_map,
            k=k,
            min_overlap=min_overlap,
        )
        row = {
            "b_id": str(case.get("b_id") or ""),
            "a_collection": str(case.get("a_collection") or ""),
            **scored,
        }
        if not scored["ok"]:
            failed += 1
        rows.append(row)
    return {
        "ok": failed == 0 and bool(rows),
        "failed": failed,
        "total": len(rows),
        "rows": rows,
    }

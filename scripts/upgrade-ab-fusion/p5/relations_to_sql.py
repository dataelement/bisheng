#!/usr/bin/env python3
"""收藏/置顶/订阅: 按用户+空间映射生成 SQL。映不上则跳过并报告, 不阻断。

置顶: user_link type=knowledge_space_pin, type_detail=空间 id
订阅: 已在 P5 写入 space_channel_member; 这里补 is_pinned
跨空间收藏引用: 用 fusion_document_map 回写 knowledgefile.reference_document_id
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PACK_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_PACK_LIB) not in sys.path:
    sys.path.insert(0, str(_PACK_LIB))

from sqlutil import escape, load_csv  # noqa: E402


def load_int_map(path: Path, a_key: str, b_key: str) -> dict[int, int]:
    out: dict[int, int] = {}
    for row in load_csv(path):
        a_raw = (row.get(a_key) or "").strip()
        b_raw = (row.get(b_key) or "").strip()
        if not a_raw or not b_raw or b_raw == "0":
            continue
        out[int(a_raw)] = int(b_raw)
    return out


def generate_sql(
    payload: dict,
    *,
    user_map: dict[int, int],
    space_map: dict[int, int],
    file_map: dict[int, int],
    doc_map: dict[int, int],
    batch_no: str,
) -> tuple[str, list[dict]]:
    skipped: list[dict] = []
    lines: list[str] = [
        f"-- generated relations batch_no={escape(batch_no)}",
        "START TRANSACTION;",
        "INSERT INTO fusion_batch (batch_no, phase, status, note) VALUES "
        f"('{escape(batch_no)}','p5_relations','open','pins/subs/favorites') "
        "ON DUPLICATE KEY UPDATE note=VALUES(note);",
    ]
    for pin in payload.get("pins") or []:
        a_uid = int(pin.get("user_id") or 0)
        a_space = int(str(pin.get("type_detail") or "0") or 0)
        b_uid = user_map.get(a_uid)
        b_space = space_map.get(a_space)
        if not b_uid or not b_space:
            skipped.append(
                {
                    "kind": "relation_unmapped",
                    "detail": f"pin a_user={a_uid} a_space={a_space}",
                }
            )
            continue
        lines.append(
            "INSERT INTO user_link (user_id, type, type_detail) "
            f"SELECT {b_uid}, 'knowledge_space_pin', '{b_space}' FROM DUAL "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM user_link WHERE user_id="
            f"{b_uid} AND type='knowledge_space_pin' AND type_detail='{b_space}');"
        )

    for row in payload.get("member_pins") or []:
        a_uid = int(row.get("user_id") or 0)
        a_space = int(row.get("business_id") or row.get("space_id") or 0)
        b_uid = user_map.get(a_uid)
        b_space = space_map.get(a_space)
        if not b_uid or not b_space:
            skipped.append(
                {
                    "kind": "relation_unmapped",
                    "detail": f"member_pin a_user={a_uid} a_space={a_space}",
                }
            )
            continue
        lines.append(
            "UPDATE space_channel_member SET is_pinned=1 "
            f"WHERE business_type='space' AND business_id='{b_space}' "
            f"AND user_id={b_uid} AND status='ACTIVE';"
        )

    for fav in payload.get("favorite_refs") or []:
        a_file = int(fav.get("id") or 0)
        a_doc = int(fav.get("reference_document_id") or 0)
        b_file = file_map.get(a_file)
        b_doc = doc_map.get(a_doc)
        if not b_file or not b_doc:
            skipped.append(
                {
                    "kind": "relation_unmapped",
                    "detail": f"favorite_ref a_file={a_file} a_doc={a_doc}",
                }
            )
            continue
        lines.append(
            f"UPDATE knowledgefile SET reference_document_id={b_doc} "
            f"WHERE id={b_file} AND (reference_document_id IS NULL OR reference_document_id<>{b_doc});"
        )

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_json", type=Path)
    parser.add_argument("--user-map", type=Path, required=True)
    parser.add_argument("--space-map", type=Path, required=True)
    parser.add_argument("--file-map", type=Path, default=None)
    parser.add_argument("--doc-map", type=Path, default=None)
    parser.add_argument("--batch-no", default="p5-relations")
    parser.add_argument("--skip-out", type=Path, default=None)
    args = parser.parse_args()
    payload = json.loads(args.export_json.read_text(encoding="utf-8"))
    sql, skipped = generate_sql(
        payload,
        user_map=load_int_map(args.user_map, "a_user_id", "b_user_id"),
        space_map=load_int_map(args.space_map, "a_space_id", "b_space_id"),
        file_map=load_int_map(args.file_map, "a_file_id", "b_file_id")
        if args.file_map
        else {},
        doc_map=load_int_map(args.doc_map, "a_doc_id", "b_doc_id")
        if args.doc_map
        else {},
        batch_no=args.batch_no,
    )
    sys.stdout.write(sql)
    if args.skip_out:
        args.skip_out.parent.mkdir(parents=True, exist_ok=True)
        args.skip_out.write_text(
            json.dumps(
                {"skipped": skipped, "count": len(skipped)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

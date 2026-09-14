#!/usr/bin/env python3
"""把 A 积分导出 JSON + 用户映射转成可审查 SQL。不连库。

- point_rule: 按 tenant_id+rule_code 用 A 覆盖 B (Q2)
- user_point_account: 按映射改 user_id 插入; B 已有则余额/累计相加, 不覆盖 B 现网账户
- user_point_log: 新发号; idempotency_key 加 fusion 前缀防撞; 映不上的用户跳过
- 不迁 point_copy / point_rank_snapshot / point_favorite_tier_award / point_sync_outbox
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_PACK_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_PACK_LIB) not in sys.path:
    sys.path.insert(0, str(_PACK_LIB))

from sqlutil import escape, load_csv, sql_int, sql_json, sql_str  # noqa: E402


def load_user_map(path: Path) -> dict[int, int]:
    out: dict[int, int] = {}
    for row in load_csv(path):
        a_id = int(row["a_user_id"])
        b_raw = (row.get("b_user_id") or "").strip()
        if not b_raw or b_raw == "0":
            continue
        out[a_id] = int(b_raw)
    return out


def remap_idempotency(batch_no: str, original: str) -> str:
    prefix = f"fm:{batch_no}:"
    raw = prefix + (original or "")
    if len(raw) <= 128:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    keep = 128 - len(prefix) - 1 - 24
    tail = (original or "")[-max(keep, 0) :]
    return f"{prefix}{digest}:{tail}"[:128]


def _dt(value: str | None) -> str:
    if not value:
        return "NULL"
    return sql_str(value.replace("T", " ")[:19])


def generate_sql(
    payload: dict, user_map: dict[int, int], batch_no: str
) -> tuple[str, list[dict]]:
    skipped: list[dict] = []
    lines: list[str] = [
        f"-- generated points batch_no={escape(batch_no)}",
        "START TRANSACTION;",
        "INSERT INTO fusion_batch (batch_no, phase, status, note) VALUES "
        f"('{escape(batch_no)}','p4_points','open','points from A') "
        "ON DUPLICATE KEY UPDATE note=VALUES(note);",
    ]
    for rule in payload.get("rules") or []:
        tenant_id = sql_int(rule.get("tenant_id"), "1")
        code = escape(rule.get("rule_code") or "")
        if not code:
            continue
        lines.append(
            "INSERT INTO point_rule "
            "(tenant_id, rule_code, rule_type, name, display_name, score_expr, "
            "daily_cap, beneficiary, status, remark, sort_order) VALUES ("
            f"{tenant_id}, '{code}', {sql_str(rule.get('rule_type') or 'earn')}, "
            f"{sql_str((rule.get('name') or code)[:40])}, "
            f"{sql_str((rule.get('display_name') or rule.get('name') or code)[:40])}, "
            f"{sql_json(rule.get('score_expr'))}, "
            f"{sql_int(rule.get('daily_cap'))}, "
            f"{sql_str(rule.get('beneficiary')) if rule.get('beneficiary') else 'NULL'}, "
            f"{sql_str(rule.get('status') or 'enabled')}, "
            f"{sql_str(rule.get('remark')) if rule.get('remark') else 'NULL'}, "
            f"{sql_int(rule.get('sort_order'), '0')}"
            ") ON DUPLICATE KEY UPDATE "
            "rule_type=VALUES(rule_type), name=VALUES(name), "
            "display_name=VALUES(display_name), score_expr=VALUES(score_expr), "
            "daily_cap=VALUES(daily_cap), beneficiary=VALUES(beneficiary), "
            "status=VALUES(status), remark=VALUES(remark), sort_order=VALUES(sort_order);"
        )

    for acc in payload.get("accounts") or []:
        a_uid = int(acc.get("user_id") or 0)
        b_uid = user_map.get(a_uid)
        if not b_uid:
            skipped.append(
                {"kind": "points_unmapped", "a_user_id": a_uid, "detail": "account"}
            )
            continue
        tenant_id = sql_int(acc.get("tenant_id"), "1")
        lines.append(
            "INSERT INTO user_point_account "
            "(tenant_id, user_id, balance, lifetime_earned, lifetime_deducted, version, last_earned_at) "
            f"VALUES ({tenant_id}, {b_uid}, {sql_int(acc.get('balance'), '0')}, "
            f"{sql_int(acc.get('lifetime_earned'), '0')}, "
            f"{sql_int(acc.get('lifetime_deducted'), '0')}, "
            f"{sql_int(acc.get('version'), '0')}, {_dt(acc.get('last_earned_at'))}) "
            "ON DUPLICATE KEY UPDATE "
            "balance=balance+VALUES(balance), "
            "lifetime_earned=lifetime_earned+VALUES(lifetime_earned), "
            "lifetime_deducted=lifetime_deducted+VALUES(lifetime_deducted), "
            "last_earned_at=IFNULL(VALUES(last_earned_at), last_earned_at);"
        )

    for log in payload.get("logs") or []:
        a_uid = int(log.get("user_id") or 0)
        b_uid = user_map.get(a_uid)
        if not b_uid:
            skipped.append(
                {
                    "kind": "points_unmapped",
                    "a_user_id": a_uid,
                    "detail": f"log idem={log.get('idempotency_key')}",
                }
            )
            continue
        op_a = log.get("operator_id")
        op_sql = "NULL"
        if op_a:
            op_b = user_map.get(int(op_a))
            op_sql = str(op_b) if op_b else "NULL"
        idem = escape(
            remap_idempotency(batch_no, str(log.get("idempotency_key") or ""))
        )
        tenant_id = sql_int(log.get("tenant_id"), "1")
        title = sql_str((log.get("title") or "fusion")[:64])
        lines.append(
            "INSERT INTO user_point_log "
            "(tenant_id, user_id, delta, balance_after, direction, rule_code, title, "
            "source, biz_type, biz_id, idempotency_key, operator_id, remark, "
            "score_snapshot, beneficiary_role, occurred_at) VALUES ("
            f"{tenant_id}, {b_uid}, {sql_int(log.get('delta'), '0')}, "
            f"{sql_int(log.get('balance_after'), '0')}, "
            f"{sql_str(log.get('direction') or 'earn')}, "
            f"{sql_str(log.get('rule_code')) if log.get('rule_code') else 'NULL'}, "
            f"{title}, {sql_str(log.get('source') or 'auto')}, "
            f"{sql_str(log.get('biz_type')) if log.get('biz_type') else 'NULL'}, "
            f"{sql_str(log.get('biz_id')) if log.get('biz_id') else 'NULL'}, "
            f"'{idem}', {op_sql}, "
            f"{sql_str(log.get('remark')) if log.get('remark') else 'NULL'}, "
            f"{sql_int(log.get('score_snapshot'))}, "
            f"{sql_str(log.get('beneficiary_role')) if log.get('beneficiary_role') else 'NULL'}, "
            f"{_dt(log.get('occurred_at'))}"
            ") ON DUPLICATE KEY UPDATE idempotency_key=idempotency_key;"
        )

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_json", type=Path)
    parser.add_argument("user_map", type=Path)
    parser.add_argument("--batch-no", default="p4-points")
    parser.add_argument("--skip-out", type=Path, default=None)
    args = parser.parse_args()
    payload = json.loads(args.export_json.read_text(encoding="utf-8"))
    sql, skipped = generate_sql(payload, load_user_map(args.user_map), args.batch_no)
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

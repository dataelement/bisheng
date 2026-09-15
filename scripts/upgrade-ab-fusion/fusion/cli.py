"""融合命令行. 在 scripts/upgrade-ab-fusion 目录执行: python3 fusion/cli.py ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
if str(PACK) not in sys.path:
    sys.path.insert(0, str(PACK))

from fusion.dry_run import dry_run_flows, dry_run_knowledge
from fusion.gaps import collect_gaps, write_gaps
from fusion.propose_dept import propose as propose_dept
from fusion.propose_model import propose as propose_model
from fusion.propose_role import propose as propose_role
from fusion.propose_server import propose as propose_server
from fusion.propose_tool import propose as propose_tool
from fusion.propose_user import propose as propose_user
from fusion.sql import load_table, write_csv
from fusion.verify_counts import (
    baseline_num,
    compare_counts,
    expected_business_counts,
    map_counts,
)


def _dump_propose(
    result: dict, out_dir: Path, stem: str, map_fields: list[str]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        out_dir / f"{stem}.proposed.csv",
        map_fields,
        result["map"],
        "人工签字后复制为 p4 正式 csv",
    )
    cfields = list(result["conflict"][0].keys()) if result["conflict"] else ["reason"]
    write_csv(out_dir / f"{stem}.conflicts.csv", cfields, result["conflict"])
    if result.get("manual"):
        write_csv(
            out_dir / f"{stem}.manual.csv",
            list(result["manual"][0].keys()),
            result["manual"],
        )
    print(
        f"map={len(result['map'])} conflict={len(result['conflict'])} manual={len(result.get('manual') or [])}"
    )
    if result["conflict"]:
        sys.exit(2)


def cmd_users_propose(args: argparse.Namespace) -> None:
    _dump_propose(
        propose_user(load_table(Path(args.a_csv)), load_table(Path(args.b_csv))),
        Path(args.out_dir),
        "user-map",
        ["b_user_id", "a_user_id", "employee_code", "action", "note"],
    )


def cmd_depts_propose(args: argparse.Namespace) -> None:
    _dump_propose(
        propose_dept(load_table(Path(args.a_csv)), load_table(Path(args.b_csv))),
        Path(args.out_dir),
        "dept-map",
        [
            "b_dept_pk",
            "a_dept_pk",
            "a_group_id",
            "external_id",
            "action",
            "b_name",
            "note",
        ],
    )


def cmd_roles_propose(args: argparse.Namespace) -> None:
    _dump_propose(
        propose_role(load_table(Path(args.a_csv)), load_table(Path(args.b_csv))),
        Path(args.out_dir),
        "role-map",
        ["b_role_id", "a_role_id", "action", "note"],
    )


def cmd_models_propose(args: argparse.Namespace) -> None:
    _dump_propose(
        propose_model(load_table(Path(args.a_csv)), load_table(Path(args.b_csv))),
        Path(args.out_dir),
        "model-map",
        ["b_model_id", "a_model_id", "action", "note"],
    )


def cmd_servers_propose(args: argparse.Namespace) -> None:
    _dump_propose(
        propose_server(load_table(Path(args.a_csv)), load_table(Path(args.b_csv))),
        Path(args.out_dir),
        "server-map",
        ["b_server_id", "a_server_id", "action", "note"],
    )


def cmd_tools_propose(args: argparse.Namespace) -> None:
    _dump_propose(
        propose_tool(load_table(Path(args.a_csv)), load_table(Path(args.b_csv))),
        Path(args.out_dir),
        "tool-map",
        ["b_tool_id", "a_tool_id", "action", "note"],
    )


def cmd_dry_run(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    user_map: dict[str, str] = {}
    for r in load_table(Path(args.user_map)):
        if r.get("action") == "create":
            user_map[r["b_user_id"]] = r.get("a_user_id") or "__create__"
        elif r.get("a_user_id"):
            user_map[r["b_user_id"]] = r["a_user_id"]
    kn = dry_run_knowledge(
        payload.get("knowledges") or [],
        user_map,
        set(payload.get("a_space_ids") or []),
        bool(args.migrate_b_spaces),
    )
    fl = dry_run_flows(payload.get("flows") or [], user_map)
    Path(args.out).write_text(
        json.dumps({"knowledge": kn, "flows": fl}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if kn["blocked"] or fl["blocked"]:
        print("dry-run BLOCKED", file=sys.stderr)
        sys.exit(2)
    print("dry-run OK")


def cmd_gaps(args: argparse.Namespace) -> None:
    rows = collect_gaps(
        Path(args.maps), Path(args.propose_dir) if args.propose_dir else None
    )
    write_gaps(Path(args.out), rows)
    print(f"gaps={len(rows)} -> {args.out}")


def cmd_verify_counts(args: argparse.Namespace) -> None:
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    report = compare_counts(
        expected=expected_business_counts(dump, bool(args.migrate_b_spaces)),
        mapped=map_counts(Path(args.maps)),
        a_space_base=baseline_num(Path(args.a_baseline), "a_space_cnt"),
        a_space_now=baseline_num(Path(args.a_now), "a_space_cnt"),
        a_space_file_base=baseline_num(Path(args.a_baseline), "a_space_file_cnt"),
        a_space_file_now=baseline_num(Path(args.a_now), "a_space_file_cnt"),
    )
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for w in report["warns"]:
        print(f"WARN {w}", file=sys.stderr)
    if not report["ok"]:
        print("verify-counts FAIL", file=sys.stderr)
        for e in report["errors"]:
            print(e, file=sys.stderr)
        sys.exit(2)
    print("verify-counts OK")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="B->A fusion")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn, a_help, b_help in (
        ("users-propose", cmd_users_propose, "A users csv", "B users csv"),
        ("depts-propose", cmd_depts_propose, "A depts csv", "B depts csv"),
        ("roles-propose", cmd_roles_propose, "A roles csv", "B roles csv"),
        ("models-propose", cmd_models_propose, "A models csv", "B models csv"),
        (
            "servers-propose",
            cmd_servers_propose,
            "A llm_server csv",
            "B llm_server csv",
        ),
        ("tools-propose", cmd_tools_propose, "A tools csv", "B tools csv"),
    ):
        s = sub.add_parser(name)
        s.add_argument("a_csv", help=a_help)
        s.add_argument("b_csv", help=b_help)
        s.add_argument("--out-dir", required=True)
        s.set_defaults(func=fn)

    dr = sub.add_parser("dry-run")
    dr.add_argument("--input", required=True)
    dr.add_argument("--user-map", required=True)
    dr.add_argument("--out", required=True)
    dr.add_argument(
        "--migrate-b-spaces", action=argparse.BooleanOptionalAction, default=False
    )
    dr.set_defaults(func=cmd_dry_run)

    gp = sub.add_parser("gaps")
    gp.add_argument("--maps", required=True)
    gp.add_argument("--propose-dir", default="")
    gp.add_argument("--out", required=True)
    gp.set_defaults(func=cmd_gaps)

    vc = sub.add_parser("verify-counts")
    vc.add_argument("--dump", required=True)
    vc.add_argument("--maps", required=True)
    vc.add_argument("--a-baseline", required=True)
    vc.add_argument("--a-now", required=True)
    vc.add_argument("--out", required=True)
    vc.add_argument(
        "--migrate-b-spaces", action=argparse.BooleanOptionalAction, default=False
    )
    vc.set_defaults(func=cmd_verify_counts)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""从 logs JSON 生成各域 SQL. python3 p5/build_sql.py --kind knowledge --dump logs/p5/dump.json --maps logs/p4 --out logs/p5/knowledge.sql"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.citation_sql import generate_citation_sql
from fusion.dictionary_sql import generate_dictionary_sql
from fusion.flow_sql import generate_assistant_sql, generate_flow_sql
from fusion.group_resource_sql import generate_group_resource_sql
from fusion.identity_sql import generate_identity_sql
from fusion.knowledge_sql import generate_knowledge_sql
from fusion.maps import load_map, persist_runtime_maps
from fusion.mark_sql import generate_mark_sql
from fusion.minio_keys import collect_map_jobs, merge_jobs_tsv
from fusion.openfga_grants import (
    dept_subjects_from_rows,
    generate_role_access_sql,
    generate_role_grant_tuples,
    remap_b_openfga_tuples,
)
from fusion.openfga_tuples import (
    assert_no_a_space_objects,
    generate_owner_tuples,
    merge_tuples,
)
from fusion.qa_sql import generate_qa_sql
from fusion.relations_sql import generate_relations_sql
from fusion.report_sql import generate_report_sql
from fusion.rollback_sql import generate_rollback_sql
from fusion.session_sql import generate_session_sql
from fusion.sql import load_csv, write_csv
from fusion.tag_sql import generate_tag_sql
from fusion.tool_type_sql import generate_tool_type_sql


def _maps(map_dir: Path) -> dict[str, dict[str, str]]:
    return {
        "user": load_map(map_dir / "user-map.csv", "b_user_id", "a_user_id"),
        "tenant": load_map(map_dir / "tenant-map.csv", "b_tenant_id", "a_tenant_id"),
        "dept": load_map(map_dir / "dept-map.csv", "b_dept_pk", "a_dept_pk"),
        "group": load_map(map_dir / "group-map.csv", "b_group_id", "a_group_id"),
        "role": load_map(map_dir / "role-map.csv", "b_role_id", "a_role_id"),
        "model": load_map(map_dir / "model-map.csv", "b_model_id", "a_model_id"),
        "llm_server": load_map(
            map_dir / "server-map.csv", "b_server_id", "a_server_id"
        ),
        "tool": load_map(map_dir / "tool-map.csv", "b_tool_id", "a_tool_id"),
        "knowledge": load_map(map_dir / "knowledge-map.csv", "b_id", "a_id"),
        "file": load_map(map_dir / "file-map.csv", "b_id", "a_id"),
        "flow": load_map(map_dir / "flow-map.csv", "b_id", "a_id"),
        "flowversion": load_map(map_dir / "flowversion-map.csv", "b_id", "a_id"),
        "assistant": load_map(map_dir / "assistant-map.csv", "b_id", "a_id"),
        "chat": load_map(map_dir / "chat-map.csv", "b_id", "a_id"),
        "message": load_map(map_dir / "message-map.csv", "b_id", "a_id"),
        "qa": load_map(map_dir / "qa-map.csv", "b_id", "a_id"),
        "review_tag": load_map(map_dir / "tag-map.csv", "b_id", "a_id"),
        "review_tag_link": load_map(map_dir / "tag-link-map.csv", "b_id", "a_id"),
        "dictionary": load_map(map_dir / "dictionary-map.csv", "b_id", "a_id"),
        "citation": load_map(map_dir / "citation-map.csv", "b_id", "a_id"),
        "citation_relation": load_map(
            map_dir / "citation-relation-map.csv", "b_id", "a_id"
        ),
        "mark_task": load_map(map_dir / "mark-task-map.csv", "b_id", "a_id"),
        "mark_record": load_map(map_dir / "mark-record-map.csv", "b_id", "a_id"),
        "mark_app_user": load_map(map_dir / "mark-app-user-map.csv", "b_id", "a_id"),
        "report": load_map(map_dir / "report-map.csv", "b_id", "a_id"),
        "group_resource": load_map(map_dir / "group-resource-map.csv", "b_id", "a_id"),
        "share_link": load_map(map_dir / "share-link-map.csv", "b_id", "a_id"),
        "tool_type": load_map(map_dir / "tool-type-map.csv", "b_id", "a_id"),
        "role_access": load_map(map_dir / "role-access-map.csv", "b_id", "a_id"),
    }


def _flush_minio_jobs(out_dir: Path, extra: dict | None, dump: dict) -> list[dict]:
    """把本域 extra 里的对象键任务追加进 minio-jobs.tsv."""
    if not extra:
        return []
    a_keys = set(dump.get("a_minio_keys") or [])
    jobs: list[dict] = []
    for key in (
        "file_maps",
        "flow_maps",
        "assistant_maps",
        "session_maps",
        "message_maps",
        "report_maps",
        "tool_type_maps",
    ):
        jobs.extend(collect_map_jobs(extra.get(key) or [], None))
    jobs.extend(extra.get("minio_jobs") or [])
    if not jobs:
        return []
    return merge_jobs_tsv(out_dir / "minio-jobs.tsv", jobs, a_keys)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", required=True)
    p.add_argument("--dump", required=True)
    p.add_argument("--maps", required=True, help="目录, 含已签字 csv")
    p.add_argument("--out", required=True)
    p.add_argument("--batch", default="fusion")
    args = p.parse_args()
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    map_dir = Path(args.maps)
    maps = _maps(map_dir)
    tenant_default = next(iter(maps["tenant"].values()), "1")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    extra: dict | None = None
    migrate_spaces = os.environ.get("MIGRATE_B_SPACES", "0") == "1"
    a_space_ids = set(dump.get("a_space_ids") or [])

    if args.kind == "identity":
        sql, extra = generate_identity_sql(
            batch=args.batch,
            tenant_map=load_csv(map_dir / "tenant-map.csv"),
            user_map=load_csv(map_dir / "user-map.csv"),
            b_users=dump.get("b_users") or [],
            a_user_names=set(dump.get("a_user_names") or []),
            next_user_id=int(dump.get("next_user_id") or 1),
            dept_map=load_csv(map_dir / "dept-map.csv"),
            next_group_id=int(dump.get("next_group_id") or 1),
            b_groups=dump.get("b_groups") or [],
            b_usergroups=dump.get("b_usergroups") or [],
            b_user_departments=dump.get("b_user_departments") or [],
            role_map=load_csv(map_dir / "role-map.csv"),
            b_roles=dump.get("b_roles") or [],
            b_userroles=dump.get("b_userroles") or [],
            next_role_id=int(dump.get("next_role_id") or 1),
            a_tenant_id=tenant_default,
        )
    elif args.kind == "dictionary":
        sql, dmaps = generate_dictionary_sql(
            batch=args.batch,
            b_rows=dump.get("dictionaries") or [],
            a_rows=dump.get("a_dictionaries") or [],
            tenant_map=maps["tenant"],
            a_existing_ids=set(dump.get("a_dictionary_ids") or []),
            next_id=int(dump.get("next_dictionary_id") or 1),
            a_tenant_default=tenant_default,
            existing_dictionary=maps["dictionary"],
        )
        extra = {"dictionary_maps": dmaps}
    elif args.kind == "knowledge":
        sql, kmaps, fmaps = generate_knowledge_sql(
            batch=args.batch,
            knowledges=dump.get("knowledges") or [],
            files=dump.get("files") or [],
            user_map=maps["user"],
            tenant_map=maps["tenant"],
            model_map=maps["model"],
            a_knowledge_names=set(dump.get("a_knowledge_names") or []),
            a_existing_ids=set(dump.get("a_existing_ids") or []),
            next_knowledge_id=int(dump.get("next_knowledge_id") or 1),
            next_file_id=int(dump.get("next_file_id") or 1),
            a_tenant_default=tenant_default,
            a_space_ids=a_space_ids,
            migrate_b_spaces=migrate_spaces,
            existing_knowledge=maps["knowledge"],
            existing_files=maps["file"],
        )
        extra = {"knowledge_maps": kmaps, "file_maps": fmaps}
    elif args.kind == "qa":
        sql, qmaps = generate_qa_sql(
            batch=args.batch,
            qas=dump.get("qas") or [],
            knowledge_map=maps["knowledge"],
            user_map=maps["user"],
            tenant_map=maps["tenant"],
            a_existing_ids=set(dump.get("a_qa_ids") or []),
            next_qa_id=int(dump.get("next_qa_id") or 1),
            a_tenant_default=tenant_default,
            existing_qa=maps["qa"],
        )
        extra = {"qa_maps": qmaps}
    elif args.kind == "tags":
        sql, tmaps, lmaps = generate_tag_sql(
            batch=args.batch,
            tags=dump.get("review_tags") or [],
            links=dump.get("review_tag_links") or [],
            maps=maps,
            a_tag_ids=set(dump.get("a_tag_ids") or []),
            a_link_ids=set(dump.get("a_tag_link_ids") or []),
            next_tag_id=int(dump.get("next_tag_id") or 1),
            next_link_id=int(dump.get("next_tag_link_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {"tag_maps": tmaps, "tag_link_maps": lmaps}
    elif args.kind == "flow":
        sql, flow_maps, version_maps, reports = generate_flow_sql(
            batch=args.batch,
            flows=dump.get("flows") or [],
            versions=dump.get("flowversions") or [],
            variables=dump.get("variables") or [],
            maps=maps,
            a_flow_ids=set(dump.get("a_flow_ids") or []),
            a_flow_names=set(dump.get("a_flow_names") or []),
            next_version_id=int(dump.get("next_version_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {
            "flow_maps": flow_maps,
            "flowversion_maps": version_maps,
            "reports": reports,
        }
    elif args.kind == "assistant":
        sql, amaps = generate_assistant_sql(
            batch=args.batch,
            assistants=dump.get("assistants") or [],
            links=dump.get("assistantlinks") or [],
            maps=maps,
            a_assistant_ids=set(dump.get("a_assistant_ids") or []),
            a_tenant_default=tenant_default,
        )
        extra = {"assistant_maps": amaps}
    elif args.kind == "session":
        sql, smaps, mmaps = generate_session_sql(
            batch=args.batch,
            sessions=dump.get("sessions") or [],
            messages=dump.get("messages") or [],
            maps=maps,
            a_chat_ids=set(dump.get("a_chat_ids") or []),
            a_session_digest=dump.get("a_session_digest") or {},
            next_message_id=int(dump.get("next_message_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {"session_maps": smaps, "message_maps": mmaps}
    elif args.kind == "citations":
        sql, cmaps, rmaps = generate_citation_sql(
            batch=args.batch,
            citations=dump.get("citations") or [],
            relations=dump.get("citation_relations") or [],
            maps=maps,
            a_citation_ids=set(str(x) for x in dump.get("a_citation_ids") or []),
            a_citation_pks=set(dump.get("a_citation_pks") or []),
            a_relation_ids=set(dump.get("a_citation_relation_ids") or []),
            next_citation_id=int(dump.get("next_citation_id") or 1),
            next_relation_id=int(dump.get("next_citation_relation_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {"citation_maps": cmaps, "citation_relation_maps": rmaps}
    elif args.kind == "marks":
        sql, tmaps, rmaps, amaps = generate_mark_sql(
            batch=args.batch,
            tasks=dump.get("mark_tasks") or [],
            records=dump.get("mark_records") or [],
            app_users=dump.get("mark_app_users") or [],
            maps=maps,
            a_task_ids=set(dump.get("a_mark_task_ids") or []),
            a_record_ids=set(dump.get("a_mark_record_ids") or []),
            a_app_user_ids=set(dump.get("a_mark_app_user_ids") or []),
            next_task_id=int(dump.get("next_mark_task_id") or 1),
            next_record_id=int(dump.get("next_mark_record_id") or 1),
            next_app_user_id=int(dump.get("next_mark_app_user_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {
            "mark_task_maps": tmaps,
            "mark_record_maps": rmaps,
            "mark_app_user_maps": amaps,
        }
    elif args.kind == "reports":
        sql, rmaps = generate_report_sql(
            batch=args.batch,
            reports=dump.get("reports") or [],
            maps=maps,
            a_existing_ids=set(dump.get("a_report_ids") or []),
            a_version_keys=set(dump.get("a_report_version_keys") or []),
            next_id=int(dump.get("next_report_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {"report_maps": rmaps}
    elif args.kind == "tool_types":
        sql, tmaps, gaps = generate_tool_type_sql(
            batch=args.batch,
            rows=dump.get("tool_types") or [],
            maps=maps,
            a_existing_ids=set(dump.get("a_tool_type_ids") or []),
            a_names=set(dump.get("a_tool_type_names") or []),
            next_id=int(dump.get("next_tool_type_id") or 1),
            a_tenant_default=tenant_default,
        )
        extra = {"tool_type_maps": tmaps, "tool_type_secret_gaps": gaps}
        if gaps:
            write_csv(
                out.parent / "gaps-tool-type-secrets.tsv",
                ["kind", "b_id", "a_id", "name", "reason"],
                gaps,
                delimiter="\t",
            )
    elif args.kind == "relations":
        sql, smaps = generate_relations_sql(
            batch=args.batch,
            user_links=dump.get("user_links") or [],
            share_links=dump.get("share_links") or [],
            maps=maps,
            a_tenant_default=tenant_default,
        )
        extra = {"share_link_maps": smaps}
    elif args.kind == "group_resource":
        sql, gmaps, gtuples = generate_group_resource_sql(
            batch=args.batch,
            rows=dump.get("group_resources") or [],
            maps=maps,
            a_existing_ids=set(dump.get("a_group_resource_ids") or []),
            next_id=int(dump.get("next_group_resource_id") or 1),
            a_tenant_default=tenant_default,
            a_space_ids=a_space_ids,
        )
        extra = {"group_resource_maps": gmaps, "group_resource_tuples": gtuples}
    elif args.kind == "role_access":
        sql, ramaps = generate_role_access_sql(
            batch=args.batch,
            role_access=dump.get("role_access") or [],
            maps=maps,
            a_existing_ids=set(dump.get("a_role_access_ids") or []),
            next_id=int(dump.get("next_role_access_id") or 1),
            a_tenant_default=tenant_default,
            a_space_ids=a_space_ids,
        )
        extra = {"role_access_maps": ramaps}
    elif args.kind == "openfga":
        owners = generate_owner_tuples(
            knowledges=dump.get("knowledges") or [],
            flows=dump.get("flows") or [],
            assistants=dump.get("assistants") or [],
            maps=maps,
            migrate_b_spaces=migrate_spaces,
        )
        group_tuples = dump.get("group_resource_tuples") or []
        meta_gr = out.parent / "group_resource.sql.meta.json"
        if meta_gr.exists():
            group_tuples = (
                json.loads(meta_gr.read_text(encoding="utf-8")).get(
                    "group_resource_tuples"
                )
                or group_tuples
            )
        role_tuples = generate_role_grant_tuples(
            role_access=dump.get("role_access") or [],
            user_roles=dump.get("user_roles") or [],
            maps=maps,
            a_space_ids=a_space_ids,
        )
        dept_subjects = dept_subjects_from_rows(load_csv(map_dir / "dept-map.csv"))
        grant_tuples = remap_b_openfga_tuples(
            rows=dump.get("b_openfga_tuples") or [],
            maps=maps,
            dept_subjects=dept_subjects,
            a_space_ids=a_space_ids,
            migrate_b_spaces=migrate_spaces,
        )
        tuples = merge_tuples(owners, group_tuples, role_tuples, grant_tuples)
        assert_no_a_space_objects(tuples, a_space_ids)
        extra = {"openfga_tuples": tuples}
        sql = (
            f"-- openfga tuples={len(tuples)} owners={len(owners)} "
            f"group={len(group_tuples)} role={len(role_tuples)} dept={len(grant_tuples)}\n"
        )
    elif args.kind == "rollback":
        raw = dump.get("maps") or {}
        maps_t = {k: [tuple(x) for x in v] for k, v in raw.items()}
        sql = generate_rollback_sql(
            batch=args.batch,
            maps=maps_t,
            a_space_ids=a_space_ids,
        )
        extra = None
    else:
        raise SystemExit(f"unknown kind {args.kind}")

    out.write_text(sql, encoding="utf-8")
    persist_runtime_maps(map_dir, extra)
    if extra is not None:
        _flush_minio_jobs(out.parent, extra, dump)
        meta = Path(str(out) + ".meta.json")
        slim = {}
        for k, v in extra.items():
            if (
                isinstance(v, list)
                and v
                and isinstance(v[0], dict)
                and "extra_jobs" in v[0]
            ):
                slim[k] = [
                    {kk: vv for kk, vv in row.items() if kk != "extra_jobs"}
                    for row in v
                ]
            else:
                slim[k] = v
        meta.write_text(
            json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if extra.get("openfga_tuples") is not None:
            (out.parent / "openfga.tuples.json").write_text(
                json.dumps(extra["openfga_tuples"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

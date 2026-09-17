#!/usr/bin/env python3
"""把 p5 TSV/JSONL 收成 dump.json, 供 dry-run / build_sql."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))
from fusion.sql import load_jsonl, load_table


def _rows(d: Path, stem: str) -> list:
    jsonl = d / f"{stem}.jsonl"
    if jsonl.exists():
        return load_jsonl(jsonl)
    tsv = d / f"{stem}.tsv"
    return load_table(tsv)


def _ids(path: Path, key: str) -> list:
    if not path.exists():
        return []
    out = []
    for row in load_table(path):
        v = row.get(key) or next(iter(row.values()), "")
        if v:
            try:
                out.append(int(v))
            except ValueError:
                out.append(v)
    return out


def _int_file(path: Path, default: int = 1) -> int:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip().split()[0]
    try:
        return int(text)
    except ValueError:
        return default


def _names(path: Path, key: str) -> list[str]:
    return [str(r.get(key) or "") for r in load_table(path) if r.get(key)]


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "logs/p5")
    spaces = []
    p = d / "a-space-ids.txt"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").split():
            try:
                spaces.append(int(ln))
            except ValueError:
                pass
    dump = {
        "knowledges": _rows(d, "b-knowledge"),
        "files": _rows(d, "b-files"),
        "qas": _rows(d, "b-qaknowledge"),
        "review_tags": _rows(d, "b-review-tag"),
        "review_tag_links": _rows(d, "b-review-tag-link"),
        "group_resources": _rows(d, "b-group-resource"),
        "dictionaries": _rows(d, "b-dictionary"),
        "a_dictionaries": _rows(d, "a-dictionary"),
        "flows": _rows(d, "b-flows"),
        "flowversions": _rows(d, "b-flowversions"),
        "variables": _rows(d, "b-variables"),
        "assistants": _rows(d, "b-assistants"),
        "assistantlinks": _rows(d, "b-assistantlinks"),
        "sessions": _rows(d, "b-sessions"),
        "messages": _rows(d, "b-messages"),
        "user_links": _rows(d, "b-user-links"),
        "share_links": _rows(d, "b-share-links"),
        "citations": _rows(d, "b-citations"),
        "citation_relations": _rows(d, "b-citation-relations"),
        "mark_tasks": _rows(d, "b-mark-tasks"),
        "mark_records": _rows(d, "b-mark-records"),
        "mark_app_users": _rows(d, "b-mark-app-users"),
        "reports": _rows(d, "b-reports"),
        "tool_types": _rows(d, "b-tool-types"),
        "role_access": _rows(d, "b-roleaccess"),
        "user_roles": _rows(d, "b-userroles"),
        "audits": _rows(d, "b-audit"),
        "b_openfga_tuples": _rows(d, "b-openfga-tuples"),
        "a_knowledge_names": _names(d / "a-knowledge.tsv", "name"),
        "a_existing_ids": _ids(d / "a-knowledge.tsv", "id"),
        "a_space_ids": spaces,
        "a_flow_ids": [str(x) for x in _ids(d / "a-flow-ids.tsv", "id")],
        "a_flow_names": _names(d / "a-flow-names.tsv", "name"),
        "a_chat_ids": [str(x) for x in _ids(d / "a-chat-ids.tsv", "chat_id")],
        "a_message_ids": _ids(d / "a-message-ids.tsv", "id"),
        "a_assistant_ids": [str(x) for x in _ids(d / "a-assistant-ids.tsv", "id")],
        "a_qa_ids": _ids(d / "a-qa-ids.tsv", "id"),
        "a_tag_ids": _ids(d / "a-tag-ids.tsv", "id"),
        "a_tag_link_ids": _ids(d / "a-tag-link-ids.tsv", "id"),
        "a_group_resource_ids": _ids(d / "a-group-resource-ids.tsv", "id"),
        "a_dictionary_ids": _ids(d / "a-dictionary.tsv", "id"),
        "a_citation_pks": _ids(d / "a-citation-ids.tsv", "id"),
        "a_citation_ids": [
            str(x) for x in _ids(d / "a-citation-cids.tsv", "citation_id")
        ],
        "a_citation_relation_ids": _ids(d / "a-citation-relation-ids.tsv", "id"),
        "a_mark_task_ids": _ids(d / "a-mark-task-ids.tsv", "id"),
        "a_mark_record_ids": _ids(d / "a-mark-record-ids.tsv", "id"),
        "a_mark_app_user_ids": _ids(d / "a-mark-app-user-ids.tsv", "id"),
        "a_report_ids": _ids(d / "a-report-ids.tsv", "id"),
        "a_report_version_keys": _names(d / "a-report-keys.tsv", "version_key"),
        "a_tool_type_ids": _ids(d / "a-tool-type-ids.tsv", "id"),
        "a_tool_type_names": _names(d / "a-tool-type-names.tsv", "name"),
        "a_role_access_ids": _ids(d / "a-role-access-ids.tsv", "id"),
        "a_audit_ids": [str(x) for x in _ids(d / "a-audit-ids.tsv", "id")],
        "a_session_digest": {},
        "next_knowledge_id": _int_file(d / "next-knowledge-id.txt"),
        "next_file_id": _int_file(d / "next-file-id.txt"),
        "next_version_id": _int_file(d / "next-version-id.txt"),
        "next_message_id": _int_file(d / "next-message-id.txt"),
        "next_qa_id": _int_file(d / "next-qa-id.txt"),
        "next_tag_id": _int_file(d / "next-tag-id.txt"),
        "next_tag_link_id": _int_file(d / "next-tag-link-id.txt"),
        "next_group_resource_id": _int_file(d / "next-group-resource-id.txt"),
        "next_dictionary_id": _int_file(d / "next-dictionary-id.txt"),
        "next_citation_id": _int_file(d / "next-citation-id.txt"),
        "next_citation_relation_id": _int_file(d / "next-citation-relation-id.txt"),
        "next_mark_task_id": _int_file(d / "next-mark-task-id.txt"),
        "next_mark_record_id": _int_file(d / "next-mark-record-id.txt"),
        "next_mark_app_user_id": _int_file(d / "next-mark-app-user-id.txt"),
        "next_report_id": _int_file(d / "next-report-id.txt"),
        "next_tool_type_id": _int_file(d / "next-tool-type-id.txt"),
        "next_role_access_id": _int_file(d / "next-role-access-id.txt"),
        "a_minio_keys": [],
    }
    out = d / "dump.json"
    out.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()

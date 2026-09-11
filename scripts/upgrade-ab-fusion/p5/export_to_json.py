#!/usr/bin/env python3
"""把 A 侧 TSV dump 拼成一个空间的 JSON。不连库。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _cell(value: str):
    if value in {"", r"\N", "NULL"}:
        return None
    return value


def _parse_section(text: str) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        rows.append([_cell(c) for c in line.split("\t")])
    return rows


def _files(rows: list[list[str | None]]) -> list[dict]:
    out = []
    for r in rows:
        if len(r) < 21:
            continue
        out.append(
            {
                "id": int(r[0]),
                "user_id": int(r[1]) if r[1] else None,
                "user_name": r[2],
                "knowledge_id": int(r[3]) if r[3] else None,
                "file_name": r[4],
                "file_type": int(r[5] or 1),
                "file_source": r[6],
                "level": int(r[7] or 0),
                "file_level_path": r[8],
                "file_size": int(r[9]) if r[9] else None,
                "md5": r[10],
                "status": int(r[11]) if r[11] else None,
                "object_name": r[12],
                "parse_type": r[13],
                "remark": r[14],
                "updater_id": int(r[15]) if r[15] else None,
                "updater_name": r[16],
                "original_uploader_id": int(r[17]) if r[17] else None,
                "reference_document_id": int(r[18]) if r[18] else None,
                "predecessor_logic_file_id": int(r[19]) if r[19] else None,
                "entry_type": r[20],
                "entry_status": r[21] if len(r) > 21 else None,
            }
        )
    return out


def assemble(dump_text: str) -> dict:
    parts: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in dump_text.splitlines():
        if line.startswith("===") and line.endswith("==="):
            if current is not None:
                parts[current] = "\n".join(buf)
            current = line.strip("=").strip()
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        parts[current] = "\n".join(buf)

    space_rows = _parse_section(parts.get("SPACE", ""))
    if not space_rows:
        raise SystemExit("dump 缺少 SPACE 段")
    s = space_rows[0]
    scope_rows = _parse_section(parts.get("SCOPE", ""))
    scope = None
    if scope_rows:
        sc = scope_rows[0]
        scope = {
            "space_id": int(sc[0]) if sc[0] else None,
            "level": sc[1],
            "owner_type": sc[2],
            "owner_id": int(sc[3]) if sc[3] else None,
        }
    members = []
    for r in _parse_section(parts.get("MEMBERS", "")):
        if len(r) < 3:
            continue
        members.append(
            {
                "user_id": int(r[0]),
                "user_role": r[1],
                "status": r[2],
                "grant_subject_type": r[3] if len(r) > 3 else None,
                "grant_subject_id": int(r[4]) if len(r) > 4 and r[4] else None,
                "grant_relation": r[5] if len(r) > 5 else None,
            }
        )
    docs = []
    for r in _parse_section(parts.get("DOCS", "")):
        if len(r) < 5:
            continue
        docs.append(
            {
                "id": int(r[0]),
                "knowledge_id": int(r[1]) if r[1] else None,
                "file_level_path": r[2],
                "level": int(r[3] or 0),
                "primary_version_id": int(r[4]) if r[4] else None,
                "predecessor_logic_file_id": int(r[5]) if len(r) > 5 and r[5] else None,
                "content_generation": int(r[6] or 0) if len(r) > 6 else 0,
                "lifecycle_status": r[7] if len(r) > 7 else "active",
            }
        )
    versions = []
    for r in _parse_section(parts.get("VERSIONS", "")):
        if len(r) < 5:
            continue
        versions.append(
            {
                "id": int(r[0]),
                "document_id": int(r[1]),
                "knowledge_file_id": int(r[2]),
                "version_no": int(r[3] or 1),
                "is_primary": str(r[4]) in {"1", "true", "True"},
            }
        )
    return {
        "space": {
            "id": int(s[0]),
            "name": s[1],
            "description": s[2],
            "user_id": int(s[3]) if s[3] else None,
            "type": int(s[4] or 3),
            "state": int(s[5] or 0) if s[5] else 0,
            "is_released": str(s[6]) in {"1", "true", "True"} if len(s) > 6 else False,
            "auth_type": s[7] if len(s) > 7 else "public",
            "icon": s[8] if len(s) > 8 else None,
        },
        "scope": scope,
        "files": _files(_parse_section(parts.get("FILES", ""))),
        "documents": docs,
        "versions": versions,
        "members": members,
    }


def main() -> None:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    payload = assemble(src.read_text(encoding="utf-8"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    files = payload["files"]
    print(
        f"a_space_id={payload['space']['id']} files={len(files)} "
        f"dirs={sum(1 for f in files if f['file_type'] == 0)} "
        f"members={len(payload['members'])} -> {dst}"
    )


if __name__ == "__main__":
    main()

"""Shared helpers for public-tag-library backup / rollback / migrate scripts.

Backup copies each live table to ``<table>_bak``. Rollback renames the live
table to ``<table>_ori`` and the backup to the original name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import text
from sqlmodel import select

from bisheng.core.database.dialect_helpers import get_dialect_name, table_exists
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.models.knowledge_tag_library_link import KnowledgeTagLibraryLink

GENERAL_LIBRARY_NAME = "通用标签库"
MAX_LIBRARY_TAGS = 999
SPACE_TYPE = 3

BACKUP_TABLES = (
    "tag",
    "knowledge_tag_library_link",
    "knowledge_space_tag_library",
)

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def bak_name(table: str) -> str:
    return f"{table}_bak"


def ori_name(table: str) -> str:
    return f"{table}_ori"


def _require_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"refusing to use identifier {name!r}")
    return name


def dialect_name(session) -> str:
    return get_dialect_name(session.get_bind())


def quote_ident(session, name: str) -> str:
    _require_ident(name)
    dialect = dialect_name(session)
    if dialect in ("mysql", "mariadb"):
        return f"`{name}`"
    return f'"{name}"'


def has_table(session, name: str) -> bool:
    _require_ident(name)
    return table_exists(session.get_bind(), name)


def count_rows(session, table: str) -> int:
    quoted = quote_ident(session, table)
    return int(session.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar() or 0)


def fetch_tag_library_tags(session, tenant_id: int | None = None) -> list[Tag]:
    statement = select(Tag).where(Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value)
    if tenant_id is not None:
        statement = statement.where(Tag.tenant_id == tenant_id)
    statement = statement.order_by(Tag.id)
    return list(session.exec(statement).all())


def fetch_links(session, tenant_id: int | None = None) -> list[KnowledgeTagLibraryLink]:
    statement = select(KnowledgeTagLibraryLink)
    if tenant_id is not None:
        statement = statement.where(KnowledgeTagLibraryLink.tenant_id == tenant_id)
    statement = statement.order_by(KnowledgeTagLibraryLink.id)
    return list(session.exec(statement).all())


def fetch_libraries(session, tenant_id: int | None = None) -> list[KnowledgeSpaceTagLibrary]:
    statement = select(KnowledgeSpaceTagLibrary)
    if tenant_id is not None:
        statement = statement.where(KnowledgeSpaceTagLibrary.tenant_id == tenant_id)
    statement = statement.order_by(KnowledgeSpaceTagLibrary.id)
    return list(session.exec(statement).all())


def public_libraries(libraries: Iterable[KnowledgeSpaceTagLibrary]) -> list[KnowledgeSpaceTagLibrary]:
    return [row for row in libraries if row.owner_knowledge_id is None]


def inspect_backup_state(session) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for table in BACKUP_TABLES:
        live = has_table(session, table)
        bak = has_table(session, bak_name(table))
        ori = has_table(session, ori_name(table))
        rows.append(
            {
                "table": table,
                "live": live,
                "bak": bak,
                "ori": ori,
                "live_rows": count_rows(session, table) if live else None,
                "bak_rows": count_rows(session, bak_name(table)) if bak else None,
            }
        )
    return rows


def _exec_ddl(session, sql: str) -> None:
    session.execute(text(sql))
    session.commit()


def _drop_table(session, name: str) -> None:
    quoted = quote_ident(session, name)
    _exec_ddl(session, f"DROP TABLE IF EXISTS {quoted}")


def create_backup_tables(session, *, force: bool) -> list[dict[str, object]]:
    missing = [table for table in BACKUP_TABLES if not has_table(session, table)]
    if missing:
        raise RuntimeError(f"source tables missing: {', '.join(missing)}")

    existing_bak = [bak_name(table) for table in BACKUP_TABLES if has_table(session, bak_name(table))]
    if existing_bak and not force:
        raise RuntimeError("backup tables already exist: " + ", ".join(existing_bak) + "; pass --force to replace")
    for name in existing_bak:
        _drop_table(session, name)

    dialect = dialect_name(session)
    created: list[dict[str, object]] = []
    for table in BACKUP_TABLES:
        target = bak_name(table)
        src = quote_ident(session, table)
        dst = quote_ident(session, target)
        if dialect in ("mysql", "mariadb"):
            _exec_ddl(session, f"CREATE TABLE {dst} LIKE {src}")
            session.execute(text(f"INSERT INTO {dst} SELECT * FROM {src}"))
            session.commit()
        elif dialect == "dm":
            try:
                _exec_ddl(session, f"CREATE TABLE {dst} LIKE {src}")
            except Exception:
                _exec_ddl(session, f"CREATE TABLE {dst} AS SELECT * FROM {src} WHERE 1 = 0")
            session.execute(text(f"INSERT INTO {dst} SELECT * FROM {src}"))
            session.commit()
        else:
            _exec_ddl(session, f"CREATE TABLE {dst} AS SELECT * FROM {src}")
        created.append(
            {
                "table": table,
                "backup": target,
                "rows": count_rows(session, target),
            }
        )
    return created


def rename_backup_into_place(session, *, force: bool) -> list[tuple[str, str, str]]:
    missing_live = [table for table in BACKUP_TABLES if not has_table(session, table)]
    missing_bak = [bak_name(table) for table in BACKUP_TABLES if not has_table(session, bak_name(table))]
    if missing_live:
        raise RuntimeError(f"live tables missing: {', '.join(missing_live)}")
    if missing_bak:
        raise RuntimeError(f"backup tables missing: {', '.join(missing_bak)}")

    existing_ori = [ori_name(table) for table in BACKUP_TABLES if has_table(session, ori_name(table))]
    if existing_ori and not force:
        raise RuntimeError("leftover _ori tables exist: " + ", ".join(existing_ori) + "; pass --force to drop them")
    for name in existing_ori:
        _drop_table(session, name)

    pairs = [(table, ori_name(table), bak_name(table)) for table in BACKUP_TABLES]
    dialect = dialect_name(session)
    if dialect in ("mysql", "mariadb"):
        parts: list[str] = []
        for live, ori, bak in pairs:
            parts.append(f"{quote_ident(session, live)} TO {quote_ident(session, ori)}")
            parts.append(f"{quote_ident(session, bak)} TO {quote_ident(session, live)}")
        _exec_ddl(session, "RENAME TABLE " + ", ".join(parts))
        return pairs

    for live, ori, bak in pairs:
        _exec_ddl(
            session,
            f"ALTER TABLE {quote_ident(session, live)} RENAME TO {quote_ident(session, ori)}",
        )
        _exec_ddl(
            session,
            f"ALTER TABLE {quote_ident(session, bak)} RENAME TO {quote_ident(session, live)}",
        )
    return pairs


def rebuild_library_name_lists(session, library: KnowledgeSpaceTagLibrary) -> None:
    """Align the library JSON name lists with current tag rows (same session)."""
    tags = list(
        session.exec(
            select(Tag).where(
                Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                Tag.business_id == str(library.id),
            )
        ).all()
    )
    non_ai: list[str] = []
    ai: list[str] = []
    seen_non_ai: set[str] = set()
    seen_ai: set[str] = set()
    for tag in tags:
        name = (tag.name or "").strip()
        if not name:
            continue
        if (tag.resource_type or "") == "ai_auto_tag":
            if name not in seen_ai:
                ai.append(name)
                seen_ai.add(name)
            continue
        if name not in seen_non_ai:
            non_ai.append(name)
            seen_non_ai.add(name)
    library.tags = non_ai
    library.ai_tags = ai
    library.tag_count = len(non_ai) + len(ai)
    library.ai_tag_count = len(ai)
    session.add(library)


def distinct_library_tenant_ids(session) -> list[int]:
    rows = session.exec(select(KnowledgeSpaceTagLibrary.tenant_id).distinct()).all()
    return sorted({int(row) for row in rows if row is not None})

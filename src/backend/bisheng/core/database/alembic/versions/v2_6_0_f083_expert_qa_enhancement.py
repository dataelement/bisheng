# ruff: noqa: RUF001, RUF002, RUF003
"""F083 专家问答增强：核心表补租户列、正规化邀请/采纳/转公开表，并回填存量。

Revision ID: f083_expert_qa_enhancement
Revises: f086_merge_points_qa_images
Create Date: 2026-08-13

M1：加列、建新表与索引（可重复执行）。
M2：tenant_id=1；存量题 public；有未删回答则锁定；邀请串→invite；已采纳→adopt。
新表主键用 INT，与现网 qa_question.id / qa_answer.id 对齐（design 写 BIGINT，此处不混用）。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    column_exists,
    constraint_exists,
    index_exists,
    table_exists,
)

revision: str = "f083_expert_qa_enhancement"
down_revision: str | Sequence[str] | None = "f086_merge_points_qa_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic")

_DEFAULT_TENANT = 1
_MAX_INVITES = 3
_MAX_ADOPTS = 3
_INSERT_CHUNK = 500

_EXPERT = "qa_expert"
_QUESTION = "qa_question"
_ANSWER = "qa_answer"
_COMMENT = "qa_comment"
_INVITE = "qa_question_invite"
_ADOPT = "qa_answer_adopt"
_ALIAS = "qa_anonymous_alias"
_ELIG = "qa_answer_eligibility"
_PUB_REQ = "qa_publish_request"
_PUB_APPR = "qa_publish_approver"

_NEW_TABLES = (_PUB_APPR, _PUB_REQ, _ELIG, _ALIAS, _ADOPT, _INVITE)


def _flag_col(name: str, comment: str, default: str = "0") -> sa.Column:
    """0/1 标志列；SmallInteger 以同时兼容 MySQL 与 DM8。"""
    return sa.Column(
        name,
        sa.SmallInteger(),
        nullable=False,
        server_default=sa.text(default),
        comment=comment,
    )


def _tenant_col() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Integer(),
        nullable=False,
        server_default=sa.text(str(_DEFAULT_TENANT)),
        comment="租户ID",
    )


def _add_column(table: str, column: sa.Column) -> None:
    conn = op.get_bind()
    if not table_exists(conn, table) or column_exists(conn, table, column.name):
        return
    op.add_column(table, column)


def _drop_column(table: str, name: str) -> None:
    conn = op.get_bind()
    if table_exists(conn, table) and column_exists(conn, table, name):
        op.drop_column(table, name)


def _create_index(table: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    conn = op.get_bind()
    if not table_exists(conn, table):
        return
    if index_exists(conn, table, name) or constraint_exists(conn, table, name):
        return
    op.create_index(name, table, columns, unique=unique)


def _drop_index(table: str, name: str) -> None:
    conn = op.get_bind()
    if not table_exists(conn, table):
        return
    if constraint_exists(conn, table, name):
        op.drop_constraint(name, table, type_="unique")
        return
    if index_exists(conn, table, name):
        op.drop_index(name, table_name=table)


def _pk() -> sa.Column:
    return sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID")


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        comment="创建时间",
    )


def _add_core_columns() -> None:
    _add_column(_EXPERT, _tenant_col())
    _add_column(
        _EXPERT,
        sa.Column(
            "status",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("1"),
            comment="专家状态：1有效 0停用",
        ),
    )

    _add_column(_QUESTION, _tenant_col())
    _add_column(
        _QUESTION,
        sa.Column(
            "question_type",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'public'"),
            comment="问题类型：directed/public",
        ),
    )
    _add_column(_QUESTION, _flag_col("content_locked", "首个有效回答后内容锁定"))
    _add_column(_QUESTION, _flag_col("asker_anonymous", "公开题提问者是否匿名"))
    _add_column(
        _QUESTION,
        sa.Column(
            "asker_reveal_on_public",
            sa.SmallInteger(),
            nullable=True,
            comment="定向题：转公开后是否公开提问者姓名",
        ),
    )
    _add_column(
        _QUESTION,
        sa.Column(
            "adopt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="有效采纳条数（0–3，冗余加速）",
        ),
    )
    _add_column(
        _QUESTION,
        sa.Column("resolved_at", sa.DateTime(), nullable=True, comment="首次采纳成功时间"),
    )
    _add_column(
        _QUESTION,
        sa.Column(
            "active_publish_request_id",
            sa.Integer(),
            nullable=True,
            comment="当前有效转公开申请ID（无则空）",
        ),
    )

    _add_column(_ANSWER, _tenant_col())
    _add_column(
        _ANSWER,
        sa.Column("user_id", sa.Integer(), nullable=True, comment="回答者用户ID（与专家档案关联；历史可空后回填）"),
    )
    _add_column(_ANSWER, _flag_col("anonymous", "本回答是否匿名（公开题）"))
    _add_column(
        _ANSWER,
        sa.Column(
            "reveal_on_public",
            sa.SmallInteger(),
            nullable=True,
            comment="定向题：转公开后是否公开姓名",
        ),
    )

    _add_column(_COMMENT, _tenant_col())
    _add_column(_COMMENT, _flag_col("anonymous", "评论是否匿名"))
    _add_column(
        _COMMENT,
        sa.Column(
            "reveal_on_public",
            sa.SmallInteger(),
            nullable=True,
            comment="定向阶段预存：转公开后是否公开姓名",
        ),
    )


def _create_new_tables() -> None:
    conn = op.get_bind()
    kw = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    if not table_exists(conn, _INVITE):
        op.create_table(
            _INVITE,
            _pk(),
            _tenant_col(),
            sa.Column("question_id", sa.Integer(), nullable=False, comment="问题ID"),
            sa.Column("expert_id", sa.Integer(), nullable=False, comment="专家档案ID（qa_expert.id）"),
            sa.Column("user_id", sa.Integer(), nullable=False, comment="专家对应用户ID"),
            _created_at(),
            sa.UniqueConstraint("question_id", "expert_id", name="uk_qa_invite_q_expert"),
            **kw,
        )

    if not table_exists(conn, _ADOPT):
        op.create_table(
            _ADOPT,
            _pk(),
            _tenant_col(),
            sa.Column("question_id", sa.Integer(), nullable=False, comment="问题ID"),
            sa.Column("answer_id", sa.Integer(), nullable=False, comment="回答ID"),
            sa.Column("expert_user_id", sa.Integer(), nullable=False, comment="被采纳回答者用户ID"),
            sa.Column("adopted_by", sa.Integer(), nullable=False, comment="提问者用户ID"),
            _created_at(),
            sa.UniqueConstraint("answer_id", name="uk_qa_adopt_answer"),
            sa.UniqueConstraint("question_id", "answer_id", name="uk_qa_adopt_q_answer"),
            **kw,
        )

    if not table_exists(conn, _ALIAS):
        op.create_table(
            _ALIAS,
            _pk(),
            _tenant_col(),
            sa.Column("question_id", sa.Integer(), nullable=False, comment="问题ID"),
            sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
            sa.Column("alias_ord", sa.Integer(), nullable=False, comment="分配序号（从1起，不回收）"),
            sa.Column("alias_label", sa.String(32), nullable=False, comment="匿名展示名，如匿名同事A"),
            _created_at(),
            sa.UniqueConstraint("question_id", "user_id", name="uk_qa_alias_q_user"),
            sa.UniqueConstraint("question_id", "alias_ord", name="uk_qa_alias_q_ord"),
            **kw,
        )

    if not table_exists(conn, _ELIG):
        op.create_table(
            _ELIG,
            _pk(),
            _tenant_col(),
            sa.Column("question_id", sa.Integer(), nullable=False, comment="问题ID"),
            sa.Column("user_id", sa.Integer(), nullable=False, comment="有资格专家用户ID"),
            sa.Column("source", sa.String(32), nullable=False, comment="资格来源：invited / pre_adopt_answer"),
            _created_at(),
            sa.UniqueConstraint("question_id", "user_id", name="uk_qa_elig_q_user"),
            **kw,
        )

    if not table_exists(conn, _PUB_REQ):
        op.create_table(
            _PUB_REQ,
            _pk(),
            _tenant_col(),
            sa.Column("question_id", sa.Integer(), nullable=False, comment="问题ID"),
            sa.Column("initiator_user_id", sa.Integer(), nullable=False, comment="发起人用户ID"),
            sa.Column("status", sa.String(16), nullable=False, comment="pending/approved/rejected/expired/ended"),
            sa.Column("duration_days", sa.SmallInteger(), nullable=False, comment="有效期天数：1/3/7"),
            sa.Column("expire_at", sa.DateTime(), nullable=False, comment="到期时间"),
            sa.Column(
                "extension_days",
                sa.SmallInteger(),
                nullable=False,
                server_default=sa.text("0"),
                comment="已累计延期天数（≤3）",
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="乐观锁版本",
            ),
            _created_at(),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=UPDATE_TIME_SERVER_DEFAULT,
                comment="更新时间",
            ),
            **kw,
        )

    if not table_exists(conn, _PUB_APPR):
        op.create_table(
            _PUB_APPR,
            _pk(),
            _tenant_col(),
            sa.Column("request_id", sa.Integer(), nullable=False, comment="转公开申请ID"),
            sa.Column("user_id", sa.Integer(), nullable=False, comment="审批人用户ID"),
            sa.Column("role_in_request", sa.String(16), nullable=False, comment="asker / answerer"),
            sa.Column("decision", sa.String(32), nullable=False, comment="pending/approved/rejected/default_approved"),
            sa.Column("decided_at", sa.DateTime(), nullable=True, comment="决策时间"),
            _created_at(),
            sa.UniqueConstraint("request_id", "user_id", name="uk_qa_pub_appr"),
            **kw,
        )


def _create_indexes() -> None:
    _create_index(_EXPERT, "ix_qa_expert_tenant_status", ["tenant_id", "status"])
    _create_index(_QUESTION, "ix_qa_q_tenant_type_created", ["tenant_id", "question_type", "created_at"])
    _create_index(_QUESTION, "ix_qa_q_tenant_user_created", ["tenant_id", "user_id", "created_at"])
    _create_index(_QUESTION, "ix_qa_q_tenant_locked", ["tenant_id", "content_locked"])
    _create_index(_QUESTION, "ix_qa_q_tenant_adopt", ["tenant_id", "adopt_count", "created_at"])
    _create_index(_ANSWER, "ix_qa_answer_tenant_qid_status", ["tenant_id", "question_id", "status"])
    _create_index(_ANSWER, "ix_qa_answer_tenant_user", ["tenant_id", "user_id"])
    _create_index(_INVITE, "ix_qa_invite_tenant_user", ["tenant_id", "user_id"])
    _create_index(_ADOPT, "ix_qa_adopt_q", ["question_id", "created_at"])
    _create_index(_ELIG, "ix_qa_elig_q", ["question_id"])
    _create_index(_PUB_REQ, "ix_qa_pub_q_status", ["question_id", "status"])
    _create_index(_PUB_REQ, "ix_qa_pub_expire", ["status", "expire_at"])
    _create_index(_PUB_APPR, "ix_qa_pub_appr_user", ["user_id", "decision"])


def _maybe_unique_expert_user() -> None:
    """历史无 (tenant_id, user_id) 唯一时先检测重复；有重复则跳过，不删行。"""
    conn = op.get_bind()
    name = "uk_qa_expert_tenant_user"
    if not table_exists(conn, _EXPERT):
        return
    if index_exists(conn, _EXPERT, name) or constraint_exists(conn, _EXPERT, name):
        return
    expert = sa.table(_EXPERT, sa.column("tenant_id"), sa.column("user_id"))
    dup = conn.execute(
        sa.select(expert.c.tenant_id, expert.c.user_id, sa.func.count())
        .group_by(expert.c.tenant_id, expert.c.user_id)
        .having(sa.func.count() > 1)
        .limit(1)
    ).fetchone()
    if dup is not None:
        logger.warning("F083 skip unique %s: duplicate (tenant_id, user_id) exists", name)
        return
    op.create_index(name, _EXPERT, ["tenant_id", "user_id"], unique=True)


def _parse_expert_ids(raw: str | None) -> list[int]:
    """解析 invited_experts：分号/逗号串或 JSON 数组；最多 3 个。"""
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    values: list[object] = []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                values = parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            values = []
    if not values:
        values = [part for part in re.split(r"[;,，\s]+", text) if part]
    ids: list[int] = []
    seen: set[int] = set()
    for item in values:
        try:
            expert_id = int(item)
        except (TypeError, ValueError):
            continue
        if expert_id <= 0 or expert_id in seen:
            continue
        seen.add(expert_id)
        ids.append(expert_id)
        if len(ids) >= _MAX_INVITES:
            break
    return ids


def _insert_rows(table: sa.Table, rows: list[dict]) -> None:
    if not rows:
        return
    conn = op.get_bind()
    for start in range(0, len(rows), _INSERT_CHUNK):
        conn.execute(table.insert(), rows[start : start + _INSERT_CHUNK])


def _backfill_invites() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _QUESTION) or not table_exists(conn, _INVITE):
        return
    invite_t = sa.table(
        _INVITE,
        sa.column("tenant_id"),
        sa.column("question_id"),
        sa.column("expert_id"),
        sa.column("user_id"),
    )
    existing = {
        (int(r.question_id), int(r.expert_id))
        for r in conn.execute(sa.select(invite_t.c.question_id, invite_t.c.expert_id))
    }
    expert_t = sa.table(_EXPERT, sa.column("id"), sa.column("user_id"), sa.column("tenant_id"))
    experts = {
        int(r.id): (int(r.user_id), int(r.tenant_id) if r.tenant_id is not None else _DEFAULT_TENANT)
        for r in conn.execute(sa.select(expert_t.c.id, expert_t.c.user_id, expert_t.c.tenant_id))
    }
    question_t = sa.table(
        _QUESTION,
        sa.column("id"),
        sa.column("tenant_id"),
        sa.column("invited_experts"),
    )
    rows: list[dict] = []
    skipped = 0
    for q in conn.execute(sa.select(question_t.c.id, question_t.c.tenant_id, question_t.c.invited_experts)):
        for expert_id in _parse_expert_ids(q.invited_experts):
            key = (int(q.id), expert_id)
            if key in existing:
                continue
            mapped = experts.get(expert_id)
            if mapped is None:
                skipped += 1
                continue
            user_id, _expert_tenant = mapped
            existing.add(key)
            rows.append(
                {
                    "tenant_id": int(q.tenant_id or _DEFAULT_TENANT),
                    "question_id": int(q.id),
                    "expert_id": expert_id,
                    "user_id": user_id,
                }
            )
    _insert_rows(invite_t, rows)
    if skipped:
        logger.warning("F083 invite backfill skipped %s ids with missing qa_expert", skipped)


def _backfill_adopts() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _ANSWER) or not table_exists(conn, _ADOPT):
        return
    adopt_t = sa.table(
        _ADOPT,
        sa.column("tenant_id"),
        sa.column("question_id"),
        sa.column("answer_id"),
        sa.column("expert_user_id"),
        sa.column("adopted_by"),
        sa.column("created_at"),
    )
    existing_answers = {int(r.answer_id) for r in conn.execute(sa.select(adopt_t.c.answer_id))}
    expert_t = sa.table(_EXPERT, sa.column("id"), sa.column("user_id"))
    expert_users = {int(r.id): int(r.user_id) for r in conn.execute(sa.select(expert_t.c.id, expert_t.c.user_id))}

    answer_t = sa.table(
        _ANSWER,
        sa.column("id"),
        sa.column("question_id"),
        sa.column("expert_id"),
        sa.column("user_id"),
        sa.column("status"),
        sa.column("adopted"),
        sa.column("created_at"),
        sa.column("tenant_id"),
    )
    question_t = sa.table(
        _QUESTION,
        sa.column("id"),
        sa.column("user_id"),
        sa.column("adopted_answer_id"),
        sa.column("tenant_id"),
        sa.column("adopt_count"),
        sa.column("resolved_at"),
        sa.column("status"),
    )
    # 关联查询避免 MySQL 专属 JSON 函数；布尔 adopted 按真值比较。
    stmt = (
        sa.select(
            answer_t.c.id,
            answer_t.c.question_id,
            answer_t.c.expert_id,
            answer_t.c.user_id,
            answer_t.c.status,
            answer_t.c.adopted,
            answer_t.c.created_at,
            answer_t.c.tenant_id,
            question_t.c.user_id.label("asker_id"),
            question_t.c.adopted_answer_id,
            question_t.c.tenant_id.label("q_tenant_id"),
        )
        .select_from(answer_t.join(question_t, question_t.c.id == answer_t.c.question_id))
        .where(answer_t.c.status != 3)
        .order_by(answer_t.c.question_id, answer_t.c.created_at)
    )

    by_question: dict[int, list[dict]] = {}
    skipped = 0
    for row in conn.execute(stmt):
        adopted_flag = bool(row.adopted) if row.adopted is not None else False
        is_adopted = (
            adopted_flag
            or int(row.status or 0) == 2
            or (row.adopted_answer_id is not None and int(row.adopted_answer_id) == int(row.id))
        )
        if not is_adopted:
            continue
        expert_user_id = None
        if row.user_id is not None:
            expert_user_id = int(row.user_id)
        elif row.expert_id is not None:
            expert_user_id = expert_users.get(int(row.expert_id))
        if expert_user_id is None:
            skipped += 1
            continue
        by_question.setdefault(int(row.question_id), []).append(
            {
                "tenant_id": int(row.q_tenant_id or row.tenant_id or _DEFAULT_TENANT),
                "question_id": int(row.question_id),
                "answer_id": int(row.id),
                "expert_user_id": expert_user_id,
                "adopted_by": int(row.asker_id),
                "created_at": row.created_at,
            }
        )

    rows: list[dict] = []
    question_stats: list[tuple[int, int, object]] = []
    overflow = 0
    for question_id, items in by_question.items():
        unique: list[dict] = []
        seen: set[int] = set()
        for item in items:
            if item["answer_id"] in existing_answers or item["answer_id"] in seen:
                continue
            seen.add(item["answer_id"])
            unique.append(item)
        if len(unique) > _MAX_ADOPTS:
            overflow += len(unique) - _MAX_ADOPTS
            unique = unique[:_MAX_ADOPTS]
        rows.extend(unique)
        if unique:
            question_stats.append((question_id, len(unique), unique[0]["created_at"]))

    _insert_rows(adopt_t, rows)
    for question_id, count, first_at in question_stats:
        conn.execute(
            question_t.update()
            .where(question_t.c.id == question_id)
            .values(adopt_count=count, resolved_at=first_at, status=1)
        )
    if skipped:
        logger.warning("F083 adopt backfill skipped %s answers without user mapping", skipped)
    if overflow:
        logger.warning("F083 adopt backfill truncated %s extra slots over max=3", overflow)


def _backfill_flags_and_status() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _QUESTION):
        return
    question_t = sa.table(
        _QUESTION,
        sa.column("id"),
        sa.column("status"),
        sa.column("content_locked"),
        sa.column("question_type"),
        sa.column("tenant_id"),
    )
    answer_t = sa.table(
        _ANSWER, sa.column("question_id"), sa.column("status"), sa.column("user_id"), sa.column("expert_id")
    )
    expert_t = sa.table(_EXPERT, sa.column("id"), sa.column("user_id"))

    conn.execute(question_t.update().where(question_t.c.status.in_([2, 3])).values(status=0))
    locked = sa.exists().where(answer_t.c.question_id == question_t.c.id, answer_t.c.status != 3)
    conn.execute(question_t.update().where(locked).values(content_locked=1))

    if table_exists(conn, _ANSWER) and column_exists(conn, _ANSWER, "user_id"):
        conn.execute(
            answer_t.update()
            .where(answer_t.c.user_id.is_(None), answer_t.c.expert_id.isnot(None))
            .values(
                user_id=sa.select(expert_t.c.user_id).where(expert_t.c.id == answer_t.c.expert_id).scalar_subquery()
            )
        )


def upgrade() -> None:
    """M1 DDL + M2 回填。缺表则跳过对应步骤，便于空库/重复执行。"""
    _add_core_columns()
    _create_new_tables()
    _create_indexes()
    _maybe_unique_expert_user()
    _backfill_flags_and_status()
    _backfill_invites()
    _backfill_adopts()


def downgrade() -> None:
    """删除新表/新列。status 2/3→0 无法还原，保持 0。"""
    bind = op.get_bind()
    for table in _NEW_TABLES:
        if table_exists(bind, table):
            op.drop_table(table)

    _drop_index(_EXPERT, "uk_qa_expert_tenant_user")
    _drop_index(_EXPERT, "ix_qa_expert_tenant_status")
    _drop_index(_QUESTION, "ix_qa_q_tenant_type_created")
    _drop_index(_QUESTION, "ix_qa_q_tenant_user_created")
    _drop_index(_QUESTION, "ix_qa_q_tenant_locked")
    _drop_index(_QUESTION, "ix_qa_q_tenant_adopt")
    _drop_index(_ANSWER, "ix_qa_answer_tenant_qid_status")
    _drop_index(_ANSWER, "ix_qa_answer_tenant_user")

    for name in (
        "active_publish_request_id",
        "resolved_at",
        "adopt_count",
        "asker_reveal_on_public",
        "asker_anonymous",
        "content_locked",
        "question_type",
        "tenant_id",
    ):
        _drop_column(_QUESTION, name)
    for name in ("reveal_on_public", "anonymous", "user_id", "tenant_id"):
        _drop_column(_ANSWER, name)
    for name in ("reveal_on_public", "anonymous", "tenant_id"):
        _drop_column(_COMMENT, name)
    for name in ("status", "tenant_id"):
        _drop_column(_EXPERT, name)

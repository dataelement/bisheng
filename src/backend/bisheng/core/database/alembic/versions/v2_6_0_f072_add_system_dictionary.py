"""F072: add system_dictionary table for expert position dictionaries.

Revision ID: f072_add_system_dictionary
Revises: f071_knowledge_document_distribution
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    index_exists,
    table_exists,
)

revision: str = "f072_add_system_dictionary"
down_revision: Union[str, Sequence[str], None] = "f071_knowledge_document_distribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_NAME = "system_dictionary"
_TABLE = sa.table(
    _TABLE_NAME,
    sa.column("type", sa.String(length=64)),
    sa.column("dict_key", sa.String(length=255)),
    sa.column("dict_value", sa.String(length=255)),
    sa.column("sort_order", sa.Integer()),
    sa.column("is_enabled", sa.Boolean()),
    sa.column("tenant_id", sa.Integer()),
)

_INDEXES = {
    "ix_system_dictionary_type": ["type"],
    "ix_system_dictionary_tenant_id": ["tenant_id"],
}

# Initial expert position dictionary values from the product requirement image.
_INITIAL_VALUES = {
    "expert_position": [
        "安全标准化管理",
        "职业健康管理",
        "有害气体检测工",
        "机要文书",
        "公寓管理",
        "制度管理",
        "厂容绿化管理",
        "信息调研",
        "外派人员",
        "保卫干事",
        "交通管理",
        "技防管理",
        "绩效与薪酬管理",
        "预算及分析管理",
        "设备管理",
        "电气自动化专业技术",
        "机械点检工程师",
        "工艺技术管理",
        "运营风控管理",
        "物贸--综合管理",
        "电子采购平台及电商管理",
        "大数据分析管理",
        "机械寻源管理",
        "生产材料采购",
        "物贸--工程设备采购",
        "电仪寻源管理",
        "仓储管理",
        "议题及LCA管理",
        "燃料市场分析",
    ],
    "expert_title": [
        "主任师",
        "首席技师",
        "高级主任师",
        "首席证券师",
        "首钢科学家",
        "首席工程师",
        "首钢工匠",
        "股份工匠",
        "首席技能专家",
        "首席技术专家",
        "首席人力师",
    ],
    "expert_job_family": [
        "运营支撑族",
        "技能操作族",
        "业务支持族",
        "运营管控族",
        "制造技术族",
        "市场管理族",
        "设备运行族",
    ],
    "expert_job_category": [
        "业务治理类",
        "检验技能类",
        "行政管理类",
        "企业管理类",
        "党建管理类",
        "铁前技术类",
        "人力资源类",
        "财务管理类",
        "市场营销类",
        "电气技术类",
        "机械技术类",
        "轧制技术类",
        "市场采购类",
        "生产管理类",
        "冶炼技术类",
        "能源技术类",
        "自动化技术类",
        "工艺技能类",
        "设备技能类",
        "研发设计类",
        "质量技术类",
        "信息技术类",
        "检修管理类",
        "热能技术类",
        "工程管理类",
    ],
}


def _create_table() -> None:
    op.create_table(
        _TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "type",
            sa.String(length=64),
            nullable=False,
            comment="Dictionary type",
        ),
        sa.Column(
            "dict_key",
            sa.String(length=255),
            nullable=False,
            comment="Dictionary key",
        ),
        sa.Column(
            "dict_value",
            sa.String(length=255),
            nullable=False,
            comment="Dictionary value",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Sort order",
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Is enabled",
        ),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=True,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "type",
            "dict_key",
            name="uk_system_dictionary_tenant_type_dict_key",
        ),
    )


def _seed_data(connection: Connection) -> None:
    existing_keys = {
        (str(row.type), str(row.dict_key))
        for row in connection.execute(sa.select(_TABLE.c.type, _TABLE.c.dict_key).where(_TABLE.c.tenant_id == 1))
    }
    rows = []
    for dict_type, values in _INITIAL_VALUES.items():
        for index, value in enumerate(values):
            dict_key = f"{dict_type}_{index + 1:03d}"
            if (dict_type, dict_key) in existing_keys:
                continue
            rows.append(
                {
                    "type": dict_type,
                    "dict_key": dict_key,
                    "dict_value": value,
                    "sort_order": index,
                    "is_enabled": True,
                    "tenant_id": 1,
                }
            )
    if rows:
        op.bulk_insert(_TABLE, rows)


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE_NAME):
        _create_table()

    for index_name, columns in _INDEXES.items():
        if not index_exists(conn, _TABLE_NAME, index_name):
            op.create_index(index_name, _TABLE_NAME, columns, unique=False)

    _seed_data(conn)


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _TABLE_NAME):
        op.drop_table(_TABLE_NAME)

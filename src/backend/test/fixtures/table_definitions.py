"""SQLite-compatible CREATE TABLE definitions for testing.

Each table has a DDL constant that mirrors the production ORM definition but
uses SQLite-compatible syntax (no AUTO_INCREMENT, ON UPDATE CURRENT_TIMESTAMP,
ENUM, or INT UNSIGNED).

Usage:
    from test.fixtures.table_definitions import create_all_tables, create_tables

    create_all_tables(engine)                         # all tables
    create_tables(engine, 'tenant', 'department')     # specific tables

Tables from F001 (tenant, user_tenant) are extracted from test_tenant_dao.py.
Tables for F002-F008 are prepared based on production ORM definitions or PRD.

Created by F000-test-infrastructure.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# F001: Tenant tables (extracted from test_tenant_dao.py)
# ---------------------------------------------------------------------------

TABLE_TENANT = """\
CREATE TABLE IF NOT EXISTS tenant (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_code VARCHAR(64) NOT NULL UNIQUE,
    tenant_name VARCHAR(128) NOT NULL,
    logo VARCHAR(512),
    root_dept_id INTEGER,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    contact_name VARCHAR(64),
    contact_phone VARCHAR(32),
    contact_email VARCHAR(128),
    quota_config JSON,
    storage_config JSON,
    create_user INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_USER_TENANT = """\
CREATE TABLE IF NOT EXISTS user_tenant (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tenant_id INTEGER NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    last_access_time DATETIME,
    join_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(user_id, tenant_id)
)"""

# ---------------------------------------------------------------------------
# Existing tables: user, group, role, role_access, flow, knowledge
# ---------------------------------------------------------------------------

TABLE_USER = """\
CREATE TABLE IF NOT EXISTS user (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name VARCHAR(255) UNIQUE,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone_number VARCHAR(64),
    dept_id VARCHAR(255),
    remark VARCHAR(512),
    avatar VARCHAR(512),
    "delete" INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_GROUP = """\
CREATE TABLE IF NOT EXISTS "group" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name VARCHAR(255),
    remark VARCHAR(512),
    tenant_id INTEGER NOT NULL DEFAULT 1,
    visibility VARCHAR(16) NOT NULL DEFAULT 'public',
    create_user INTEGER,
    update_user INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(tenant_id, group_name)
)"""

TABLE_USERGROUP = """\
CREATE TABLE IF NOT EXISTS usergroup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    group_id INTEGER,
    is_group_admin INTEGER DEFAULT 0,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    remark VARCHAR(512),
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_ROLE = """\
CREATE TABLE IF NOT EXISTS role (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name VARCHAR(255) NOT NULL,
    group_id INTEGER,
    remark VARCHAR(512),
    knowledge_space_file_limit INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(group_id, role_name)
)"""

TABLE_ROLE_ACCESS = """\
CREATE TABLE IF NOT EXISTS role_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER,
    third_id VARCHAR(255),
    type INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_FLOW = """\
CREATE TABLE IF NOT EXISTS flow (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255),
    user_id INTEGER,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    description VARCHAR(1000),
    data JSON,
    logo VARCHAR(512),
    status INTEGER DEFAULT 1,
    flow_type INTEGER DEFAULT 10,
    guide_word VARCHAR(1000),
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_KNOWLEDGE = """\
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(200) NOT NULL,
    type INTEGER DEFAULT 0,
    description VARCHAR(512),
    model VARCHAR(255),
    collection_name VARCHAR(255),
    index_name VARCHAR(255),
    state INTEGER DEFAULT 1,
    is_released INTEGER DEFAULT 0,
    auth_type VARCHAR(32) DEFAULT 'public',
    metadata_fields JSON,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

# ---------------------------------------------------------------------------
# F002 preparation: department tables (based on PRD, not yet in production)
# F002-department-tree will create the real ORM; update DDL here to match.
# ---------------------------------------------------------------------------

TABLE_DEPARTMENT = """\
CREATE TABLE IF NOT EXISTS department (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    parent_id INTEGER,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    path VARCHAR(512) NOT NULL DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    source VARCHAR(32) DEFAULT 'local',
    external_id VARCHAR(128),
    status VARCHAR(16) DEFAULT 'active',
    default_role_ids JSON,
    create_user INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(source, external_id)
)"""

TABLE_USER_DEPARTMENT = """\
CREATE TABLE IF NOT EXISTS user_department (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    is_primary INTEGER DEFAULT 1,
    source VARCHAR(32) DEFAULT 'local',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(user_id, department_id)
)"""

# ---------------------------------------------------------------------------
# Registry & helpers
# ---------------------------------------------------------------------------

TABLE_DEFINITIONS: dict[str, str] = {
    'tenant': TABLE_TENANT,
    'user_tenant': TABLE_USER_TENANT,
    'user': TABLE_USER,
    'group': TABLE_GROUP,
    'usergroup': TABLE_USERGROUP,
    'role': TABLE_ROLE,
    'role_access': TABLE_ROLE_ACCESS,
    'flow': TABLE_FLOW,
    'knowledge': TABLE_KNOWLEDGE,
    'department': TABLE_DEPARTMENT,
    'user_department': TABLE_USER_DEPARTMENT,
}


def create_all_tables(engine: Engine) -> None:
    """Create all registered tables in the given engine."""
    with engine.begin() as conn:
        for ddl in TABLE_DEFINITIONS.values():
            conn.execute(text(ddl))


def create_tables(engine: Engine, *table_names: str) -> None:
    """Create only the specified tables.

    Raises KeyError if a table name is not in TABLE_DEFINITIONS.
    """
    with engine.begin() as conn:
        for name in table_names:
            conn.execute(text(TABLE_DEFINITIONS[name]))

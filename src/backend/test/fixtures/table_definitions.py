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
    parent_tenant_id INTEGER,
    share_default_to_children INTEGER NOT NULL DEFAULT 1,
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
    is_active INTEGER,
    last_access_time DATETIME,
    join_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(user_id, is_active)
)"""

# ---------------------------------------------------------------------------
# Existing tables: user, group, role, roleaccess, flow, knowledge
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
    source VARCHAR(32) NOT NULL DEFAULT 'local',
    external_id VARCHAR(128),
    "delete" INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS roleaccess (
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
    is_tenant_root INTEGER NOT NULL DEFAULT 0,
    mounted_tenant_id INTEGER,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    last_sync_ts BIGINT NOT NULL DEFAULT 0,
    default_role_ids JSON,
    create_user INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(source, external_id)
)"""

TABLE_AUDIT_LOG = """\
CREATE TABLE IF NOT EXISTS auditlog (
    id VARCHAR(255) PRIMARY KEY,
    operator_id INTEGER NOT NULL,
    operator_name VARCHAR(255),
    group_ids JSON,
    system_id VARCHAR(64),
    event_type VARCHAR(64),
    object_type VARCHAR(64),
    object_id VARCHAR(64),
    object_name TEXT,
    note TEXT,
    ip_address VARCHAR(64),
    tenant_id INTEGER,
    operator_tenant_id INTEGER,
    action VARCHAR(64),
    target_type VARCHAR(32),
    target_id VARCHAR(64),
    reason TEXT,
    metadata JSON,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
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
# F006 migration: additional source tables
# ---------------------------------------------------------------------------

TABLE_USER_ROLE = """\
CREATE TABLE IF NOT EXISTS userrole (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_SPACE_CHANNEL_MEMBER = """\
CREATE TABLE IF NOT EXISTS space_channel_member (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id VARCHAR(36) NOT NULL,
    business_type VARCHAR(16) NOT NULL,
    user_id INTEGER NOT NULL,
    user_role VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    is_pinned INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_KNOWLEDGE_FILE = """\
CREATE TABLE IF NOT EXISTS knowledgefile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    user_name VARCHAR(255),
    knowledge_id INTEGER NOT NULL,
    file_name VARCHAR(200) NOT NULL,
    file_type INTEGER DEFAULT 1,
    file_source VARCHAR(32),
    level INTEGER DEFAULT 0,
    file_level_path VARCHAR(512),
    status INTEGER DEFAULT 5,
    object_name VARCHAR(512),
    remark VARCHAR(512),
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

TABLE_GPTS_TOOLS = """\
CREATE TABLE IF NOT EXISTS t_gpts_tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(255),
    description TEXT,
    is_delete INTEGER DEFAULT 0,
    is_preset INTEGER DEFAULT 0,
    type INTEGER DEFAULT 0,
    extra TEXT,
    logo VARCHAR(512),
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

# Channel id is CHAR(36) in production (UUID hex). Use VARCHAR here so the
# F018 transfer flow that binds str ids into ``WHERE id IN (...)`` behaves
# the same in SQLite as in MySQL.
TABLE_CHANNEL = """\
CREATE TABLE IF NOT EXISTS channel (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(255) NOT NULL,
    logo VARCHAR(512),
    status INTEGER DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

# F018 requires the assistant table for the "assistant" transfer type.
# Production schema (src/backend/bisheng/database/models/assistant.py) uses
# UUID string ids.
TABLE_ASSISTANT = """\
CREATE TABLE IF NOT EXISTS assistant (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 0,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(255),
    logo VARCHAR(512),
    desc TEXT,
    system_prompt TEXT,
    prompt TEXT,
    model_name VARCHAR(255),
    status INTEGER DEFAULT 1,
    is_delete INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

# ---------------------------------------------------------------------------
# F004: ReBAC compensation queue
# ---------------------------------------------------------------------------

TABLE_FAILED_TUPLE = """\
CREATE TABLE IF NOT EXISTS failed_tuple (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action VARCHAR(8) NOT NULL DEFAULT 'write',
    fga_user VARCHAR(256) NOT NULL,
    relation VARCHAR(64) NOT NULL,
    object VARCHAR(256) NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
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
    'roleaccess': TABLE_ROLE_ACCESS,
    'flow': TABLE_FLOW,
    'knowledge': TABLE_KNOWLEDGE,
    'department': TABLE_DEPARTMENT,
    'user_department': TABLE_USER_DEPARTMENT,
    'auditlog': TABLE_AUDIT_LOG,
    'failed_tuple': TABLE_FAILED_TUPLE,
    # F006 migration source tables
    'userrole': TABLE_USER_ROLE,
    'space_channel_member': TABLE_SPACE_CHANNEL_MEMBER,
    'knowledgefile': TABLE_KNOWLEDGE_FILE,
    't_gpts_tools': TABLE_GPTS_TOOLS,
    'channel': TABLE_CHANNEL,
    # F018: owner transfer targets the standalone assistant table.
    'assistant': TABLE_ASSISTANT,
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

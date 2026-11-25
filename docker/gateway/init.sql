-- MySQL 8.0.16+ deployment schema for bisheng-gateway v1.9.3 (3674032d).
-- Includes all 8 business tables and fresh-install multi-node constraints.
-- Existing tables/data are preserved; IF NOT EXISTS does not repair schema drift.
-- See ../README.md for existing-schema upgrades and one-time index migration.
CREATE DATABASE IF NOT EXISTS bisheng_gateway
    CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE bisheng_gateway;

CREATE TABLE IF NOT EXISTS gt_group_resource (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_id INT NOT NULL,
    resource_id VARCHAR(256) NOT NULL,
    resource_limit INT NOT NULL DEFAULT 0,
    resource_type TINYINT NOT NULL
);
CREATE TABLE IF NOT EXISTS gt_sensitive_words (
    id INT AUTO_INCREMENT PRIMARY KEY,
    resource_id VARCHAR(256) NOT NULL,
    resource_type TINYINT,
    auto_words TEXT,
    words TEXT,
    words_types VARCHAR(32),
    is_check TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    logic_delete TINYINT NOT NULL DEFAULT 0,
    auto_reply VARCHAR(128),
    gateway_active_slot TINYINT GENERATED ALWAYS AS
        (CASE WHEN logic_delete = 0 THEN 1 ELSE NULL END) STORED,
    CONSTRAINT ck_gt_sensitive_active_type CHECK (logic_delete <> 0 OR resource_type IS NOT NULL),
    UNIQUE INDEX uq_gt_sensitive_active_identity (resource_id, resource_type, gateway_active_slot)
);
CREATE TABLE IF NOT EXISTS gt_user_group (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_name VARCHAR(256) NOT NULL,
    admin_user VARCHAR(512),
    admin_user_id VARCHAR(512),
    group_limit INT NOT NULL DEFAULT 0,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    logic_delete TINYINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gt_block_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(64),
    user_input TEXT,
    system_out TEXT,
    block_words TEXT,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    resource_id VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS gt_department (
    id INT PRIMARY KEY,
    dept_name VARCHAR(256) NOT NULL,
    dept_limit INT NOT NULL DEFAULT 0,
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS gt_department_resource (
    id INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    resource_id VARCHAR(256) NOT NULL,
    resource_limit INT NOT NULL DEFAULT 0,
    resource_type TINYINT NOT NULL,
    INDEX idx_dept_resource (department_id, resource_id),
    UNIQUE INDEX uq_gt_department_resource_identity (department_id, resource_type, resource_id)
);

-- DSH content safety (same definitions as the standalone additive script).
-- F111 additive schema only. Select the existing Gateway database/schema first.
-- Stop feature writers before schema operations. Application rollback keeps both tables.
-- Reruns skip existing tables: inspect their columns, constraints and indexes for exact
-- equivalence first; IF NOT EXISTS is not schema-drift repair. No model text/credentials.
-- All timestamps are UTC with microsecond precision, supplied explicitly by the service.
-- MySQL 8.0.16+ is required for enforced CHECK constraints.
CREATE TABLE IF NOT EXISTS gt_dsh_sensitive_policy (
    tenant_id BIGINT NOT NULL PRIMARY KEY,
    version BIGINT DEFAULT 1 NOT NULL,
    enabled SMALLINT DEFAULT 0 NOT NULL,
    input_enabled SMALLINT DEFAULT 0 NOT NULL,
    output_enabled SMALLINT DEFAULT 0 NOT NULL,
    words_types VARCHAR(256) NULL,
    custom_words MEDIUMTEXT NULL,
    auto_reply VARCHAR(2048) NULL,
    builtin_digest CHAR(64) NULL,
    updated_by BIGINT NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT ck_dsh_policy_version CHECK (version > 0),
    CONSTRAINT ck_dsh_policy_tenant CHECK (tenant_id > 0 AND updated_by > 0),
    CONSTRAINT ck_dsh_policy_flags CHECK (enabled IN (0,1) AND input_enabled IN (0,1) AND output_enabled IN (0,1)),
    INDEX ix_dsh_policy_version (tenant_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS gt_dsh_safety_outbox (
    event_id VARCHAR(36) NOT NULL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    gateway_request_id VARCHAR(36) NOT NULL,
    event_version BIGINT NOT NULL,
    payload MEDIUMTEXT NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    status VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
    attempts INT DEFAULT 0 NOT NULL,
    next_attempt_at DATETIME(6) NOT NULL,
    lease_owner VARCHAR(128) NULL,
    lease_until DATETIME(6) NULL,
    last_error_code VARCHAR(64) NULL,
    created_at DATETIME(6) NOT NULL,
    acked_at DATETIME(6) NULL,
    CONSTRAINT uq_dsh_ob_request_ver UNIQUE (source_id, gateway_request_id, event_version),
    CONSTRAINT ck_dsh_ob_identity CHECK (tenant_id > 0 AND event_version > 0),
    CONSTRAINT ck_dsh_ob_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_dsh_ob_status CHECK (status IN ('PENDING','INFLIGHT','ACKED','QUARANTINED')),
    INDEX ix_dsh_ob_claim (status, next_attempt_at, event_id),
    INDEX ix_dsh_ob_lease (status, lease_until, event_id),
    INDEX ix_dsh_ob_tenant (tenant_id, created_at, event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

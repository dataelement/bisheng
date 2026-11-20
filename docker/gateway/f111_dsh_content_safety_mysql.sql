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

-- Read-only checks for 0920 -> 909r1. Run against the real BiSheng schema.
-- Do not print config, API credentials, Bot Secrets or ciphertext columns.
-- An incomplete schema is a stop condition, not permission to create/delete data.

SELECT version_num FROM alembic_version;

SELECT COUNT(*) AS llm_server_count FROM llm_server;
SELECT COUNT(*) AS llm_model_count FROM llm_model;
SELECT COUNT(*) AS assistant_count FROM assistant;
SELECT COUNT(*) AS knowledge_count FROM knowledge;
SELECT COUNT(*) AS knowledge_file_count FROM knowledgefile;
SELECT COUNT(*) AS permission_grant_count FROM permission_grant;

-- Model records must resolve their provider. A returned row needs investigation.
SELECT m.id AS model_id, m.server_id, m.model_name, m.tenant_id
FROM llm_model m
LEFT JOIN llm_server s ON s.id = m.server_id
WHERE m.server_id IS NULL OR s.id IS NULL;

-- CURRENT must be unique; the referenced authorization release must be ACTIVE.
SELECT status, COUNT(*) AS release_count
FROM permission_catalog_release
GROUP BY status;

SELECT p.id AS catalog_id, p.release_key, p.write_fenced,
       p.required_authorization_model_release_id,
       a.store_id, a.model_id, a.model_checksum, a.status AS model_status
FROM permission_catalog_release p
LEFT JOIN authorization_model_release a
  ON a.id = p.required_authorization_model_release_id
WHERE p.status = 'CURRENT';

-- These states block permission model apply. Do not delete them to proceed.
SELECT status, COUNT(*) AS operation_count
FROM permission_projection_operation
WHERE status IN ('PREPARED', 'STAGING', 'COMMIT_UNKNOWN', 'COMMITTED')
GROUP BY status;

-- Preserve existing tenant PAT policy values across the upgrade.
-- pat_data_scope is deliberately excluded here because 0920 does not have it.
SELECT tenant_id, pat_enabled, pat_ttl_days
FROM open_api_tenant_setting
ORDER BY tenant_id;

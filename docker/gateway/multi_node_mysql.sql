-- Run multi_node_preflight.sql and resolve conflicts first. Run once in the Gateway schema.
-- No rows are deleted or deduplicated automatically. Existing gt_dsh_* tables are untouched.
CREATE UNIQUE INDEX uq_gt_department_resource_identity
ON gt_department_resource (department_id, resource_type, resource_id);
ALTER TABLE gt_sensitive_words
    ADD CONSTRAINT ck_gt_sensitive_active_type CHECK (logic_delete <> 0 OR resource_type IS NOT NULL),
    ADD COLUMN gateway_active_slot TINYINT GENERATED ALWAYS AS
        (CASE WHEN logic_delete = 0 THEN 1 ELSE NULL END) STORED;
CREATE UNIQUE INDEX uq_gt_sensitive_active_identity
ON gt_sensitive_words (resource_id, resource_type, gateway_active_slot);

-- Read-only preflight. The first three queries must return no rows before migration.
-- The last query is an informational HTTP-rate conflict report.
SELECT department_id, resource_type, resource_id, COUNT(*) AS duplicate_count
FROM gt_department_resource GROUP BY department_id, resource_type, resource_id HAVING COUNT(*) > 1;
SELECT resource_type, resource_id, COUNT(*) AS duplicate_count
FROM gt_sensitive_words WHERE logic_delete = 0 GROUP BY resource_type, resource_id HAVING COUNT(*) > 1;
SELECT id, resource_type, resource_id FROM gt_sensitive_words WHERE logic_delete = 0 AND resource_type IS NULL;
-- HTTP conflict report: review these values; runtime uses the minimum positive limit per resource.
SELECT resource_type, resource_id, MIN(resource_limit) AS effective_rate, MAX(resource_limit) AS largest_rate
FROM gt_department_resource WHERE resource_limit > 0 GROUP BY resource_type, resource_id
HAVING MIN(resource_limit) <> MAX(resource_limit);

-- P1 A（2.5.0-sg，只读）。列不存在则跳过该段并记入报告。
SET NAMES utf8mb4;

SELECT 'A_ALEMBIC' AS section;
SELECT version_num FROM alembic_version;

SELECT 'A_USER_COUNTS' AS section;
SELECT COUNT(*) AS user_total,
       SUM(CASE WHEN `delete` = 0 THEN 1 ELSE 0 END) AS user_active
FROM `user`;

SELECT 'A_USER_BY_SOURCE' AS section;
SELECT `source`, COUNT(*) AS cnt FROM `user` GROUP BY `source`;

SELECT 'A_DUP_EXT_SOURCE_PATTERN' AS section;
SELECT sources, COUNT(*) AS grp_cnt FROM (
  SELECT external_id, GROUP_CONCAT(`source` ORDER BY `source` SEPARATOR '+') AS sources
  FROM `user`
  WHERE external_id IS NOT NULL AND external_id <> ''
  GROUP BY external_id
  HAVING COUNT(*) > 1
) t
GROUP BY sources;

SELECT 'A_MISSING_EXT' AS section;
SELECT user_id, user_name, `source`, `delete`
FROM `user`
WHERE `delete` = 0 AND (external_id IS NULL OR external_id = '');

SELECT 'A_DEPT' AS section;
SELECT COUNT(*) AS dept_total,
       SUM(CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END) AS dept_active
FROM department;

SELECT 'A_KNOWLEDGE_BY_TYPE' AS section;
SELECT type, COUNT(*) AS cnt FROM knowledge GROUP BY type;

SELECT 'A_SPACE_TOP' AS section;
SELECT k.id, k.name, k.user_id, k.state,
       (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id = k.id) AS file_cnt
FROM knowledge k
WHERE k.type = 3
ORDER BY file_cnt DESC
LIMIT 50;

SELECT 'A_FILE_STATUS' AS section;
SELECT status, COUNT(*) AS cnt FROM knowledgefile GROUP BY status;

SELECT 'A_FAILED_TUPLE' AS section;
SELECT status, COUNT(*) AS cnt FROM failed_tuple GROUP BY status;

SELECT 'A_ORG_SYNC' AS section;
SELECT id, provider, config_name, status, sync_status, last_sync_at FROM org_sync_config;

SELECT 'A_TENANT' AS section;
SELECT id, tenant_code, tenant_name, status FROM tenant;

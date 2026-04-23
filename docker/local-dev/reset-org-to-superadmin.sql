-- =============================================================================
-- bisheng 库：清空「组织同步 + 部门 + 成员」相关数据，仅保留一名超级管理员
--
-- 保留用户规则（与产品约定一致）：
--   1) 优先保留「已绑定 role_id = 1（AdminRole）」中 user_id 最小的一名用户；
--   2) 若无人拥有 role_id=1，则保留 user 表中 user_id 最小的一行（兜底）。
--
-- 会删除 / 清空：
--   org_sync_log / org_sync_config、department*、user_department、
--   除保留用户外的 user 及依赖外键的子表（channel、linsight_*、usergroup、userrole）、
--   user_link（非保留用户）、user_tenant（全表后仅为保留用户重建一条根租户记录）、invitecode 全表。
--
-- 不会动：tenant、role、知识库 flow 等业务主数据（仅去掉部门挂载关系）。
--
-- 执行前务必备份：
--   docker exec bisheng-mysql mysqldump -uroot -p1234 bisheng > backup-bisheng.sql
--
-- 执行示例（仓库根目录）：
--   docker exec -i bisheng-mysql mysql -uroot -p1234 bisheng < docker/local-dev/reset-org-to-superadmin.sql
--
-- OpenFGA / Redis 中的权限元组或 org_sync 锁不会由此脚本清理；若你启用了 FGA，
-- 清理后请在文档环境执行一次全量同步或按运维流程重建元组。
-- =============================================================================

SET NAMES utf8mb4;
SET @keep := (
  SELECT COALESCE(
    (SELECT MIN(ur.user_id) FROM userrole ur WHERE ur.role_id = 1),
    (SELECT MIN(u.user_id) FROM `user` u)
  )
);

-- 空库保护：没有用户则只清组织表，不删 user
DELETE FROM org_sync_log;
DELETE FROM org_sync_config;

DELETE FROM department_knowledge_space;
DELETE FROM user_department;
DELETE FROM `department`;

DELETE FROM invitecode;

DELETE FROM user_link WHERE @keep IS NOT NULL AND user_id <> @keep;
DELETE FROM user_tenant WHERE @keep IS NOT NULL;

DELETE FROM channel WHERE @keep IS NOT NULL AND user_id <> @keep;
DELETE FROM linsight_session_version WHERE @keep IS NOT NULL AND user_id <> @keep;
DELETE FROM linsight_sop WHERE @keep IS NOT NULL AND user_id <> @keep;
DELETE FROM linsight_sop_record WHERE @keep IS NOT NULL AND user_id <> @keep;

DELETE FROM usergroup WHERE @keep IS NOT NULL AND user_id <> @keep;
DELETE FROM userrole WHERE @keep IS NOT NULL AND user_id <> @keep;

DELETE FROM `user` WHERE @keep IS NOT NULL AND user_id <> @keep;

INSERT INTO user_tenant (user_id, tenant_id, is_default, status, is_active)
SELECT @keep, 1, 1, 'active', 1
FROM DUAL
WHERE @keep IS NOT NULL;

DELETE FROM userrole WHERE @keep IS NOT NULL AND user_id = @keep AND role_id <> 1;

INSERT INTO userrole (user_id, role_id, tenant_id)
SELECT @keep, 1, 1
FROM DUAL
WHERE @keep IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM userrole ur WHERE ur.user_id = @keep AND ur.role_id = 1);

SELECT @keep AS kept_user_id, (SELECT COUNT(*) FROM `user`) AS remaining_users;

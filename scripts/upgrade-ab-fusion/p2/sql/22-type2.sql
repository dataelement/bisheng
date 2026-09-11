-- D07：有效 type=2 转为个人知识空间。空库/无主不删除，只转换仍为 type=2 的行。
-- 官方把所有 type=2 改名为「个人知识空间」，会撞名。本包保留原 name，只改 type/auth_type。
-- status：2.4 官方插入 1；2.5-sg 模型是 ACTIVE。本步在 2.4 镜像之后执行，用 1。
-- 2.5 Alembic 若改枚举，由 30-hop-2.5 处理。

UPDATE knowledge
SET type = 3, auth_type = 'PRIVATE'
WHERE type = 2;

INSERT INTO space_channel_member (business_id, business_type, user_id, user_role, status)
SELECT k.id, 'SPACE', k.user_id, 'CREATOR', 1
FROM knowledge k
WHERE k.type = 3
  AND k.user_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM space_channel_member m
    WHERE m.business_type = 'SPACE' AND m.business_id = k.id AND m.user_id = k.user_id
  );

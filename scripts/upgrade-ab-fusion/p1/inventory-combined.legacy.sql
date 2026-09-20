-- 毕昇 A/B 融合 P1 只读盘点
-- 基线：毕昇A-B环境升级融合方案-客户评审版.md 第 4.2 / 5.3 / 6 / 7 节
-- 只读。不要在生产上跑 UPDATE/INSERT。A=2.5.0-sg，B=2.2。两边库各跑对应段落。
-- 结果导出后整理成：用户映射、部门映射、资源/ID 映射、冲突/客户决策 四份清单。

-- ============================================================
-- B 环境（2.2）
-- ============================================================

-- B-1 用户
SELECT COUNT(*) AS user_total,
       SUM(CASE WHEN `delete` = 0 THEN 1 ELSE 0 END) AS user_active,
       SUM(CASE WHEN `delete` <> 0 THEN 1 ELSE 0 END) AS user_deleted
FROM `user`;

SELECT user_id, user_name, email, phone_number, dept_id, `delete`, create_time
FROM `user`
ORDER BY user_id;

-- 登录名重复（2.2 user_name 本应唯一，有重复即冲突）
SELECT user_name, COUNT(*) AS cnt
FROM `user`
GROUP BY user_name
HAVING COUNT(*) > 1;

SELECT email, COUNT(*) AS cnt
FROM `user`
WHERE email IS NOT NULL AND email <> ''
GROUP BY email
HAVING COUNT(*) > 1;

SELECT phone_number, COUNT(*) AS cnt
FROM `user`
WHERE phone_number IS NOT NULL AND phone_number <> ''
GROUP BY phone_number
HAVING COUNT(*) > 1;

-- B-2 角色 / 用户组 / 无主资源线索
SELECT COUNT(*) FROM `role`;
SELECT COUNT(*) FROM `userrole`;
SELECT COUNT(*) FROM `group`;
SELECT COUNT(*) FROM `usergroup`;

-- B-3 工作流 / 助手 / 工具
SELECT flow_type, COUNT(*) AS cnt FROM flow GROUP BY flow_type;
SELECT COUNT(*) FROM flowversion;
SELECT COUNT(*) FROM assistant;
SELECT COUNT(*) FROM t_gpts_tools;
SELECT COUNT(*) FROM t_gpts_tools_type;

-- B-4 传统知识库（评审稿 5.3：必须查 type=2）
SELECT type, COUNT(*) AS knowledge_cnt
FROM knowledge
GROUP BY type;

SELECT k.id, k.name, k.type, k.user_id, k.state,
       (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id = k.id) AS file_cnt
FROM knowledge k
WHERE k.type = 2
ORDER BY k.id;

-- type=2 且无文件：异常清单候选，不自动删
SELECT k.id, k.name, k.user_id
FROM knowledge k
WHERE k.type = 2
  AND NOT EXISTS (SELECT 1 FROM knowledgefile f WHERE f.knowledge_id = k.id);

SELECT COUNT(*) FROM knowledgefile;
SELECT knowledge_id, COUNT(*) AS file_cnt
FROM knowledgefile
GROUP BY knowledge_id
ORDER BY file_cnt DESC
LIMIT 50;

-- B-5 会话（默认不迁 A 的会话；B 自己升级要保留，只做基线数量）
SELECT COUNT(*) FROM message_session;
SELECT COUNT(*) FROM chatmessage;

-- B-6 无主：资源 user_id 在 user 表不存在
SELECT 'flow' AS kind, COUNT(*) AS cnt
FROM flow f LEFT JOIN `user` u ON f.user_id = u.user_id
WHERE f.user_id IS NOT NULL AND u.user_id IS NULL
UNION ALL
SELECT 'knowledge', COUNT(*)
FROM knowledge k LEFT JOIN `user` u ON k.user_id = u.user_id
WHERE k.user_id IS NOT NULL AND u.user_id IS NULL;

-- ============================================================
-- A 环境（2.5.0-sg）
-- 若列不存在（例如尚未上某条 alembic），跳过该条并记入盘点报告。
-- ============================================================

-- A-1 升级水位
SELECT version_num FROM alembic_version;

-- A-2 用户 / 身份（评审稿 6.2：员工编码）
SELECT COUNT(*) AS user_total,
       SUM(CASE WHEN `delete` = 0 THEN 1 ELSE 0 END) AS user_active
FROM `user`;

SELECT `source`, COUNT(*) AS cnt
FROM `user`
GROUP BY `source`;

SELECT COUNT(*) AS missing_external_id
FROM `user`
WHERE `delete` = 0
  AND (external_id IS NULL OR external_id = '');

SELECT external_id, COUNT(*) AS cnt
FROM `user`
WHERE external_id IS NOT NULL AND external_id <> ''
GROUP BY external_id
HAVING COUNT(*) > 1;

SELECT user_id, user_name, `source`, external_id, external_code, email, phone_number, `delete`
FROM `user`
ORDER BY user_id;

-- A-3 部门
SELECT COUNT(*) FROM department;

-- 按实际表结构调整；external_id 列名以 A 库 DESCRIBE department 为准
-- SELECT external_id, COUNT(*) FROM department
-- WHERE external_id IS NOT NULL AND external_id <> ''
-- GROUP BY external_id HAVING COUNT(*) > 1;

-- A-4 知识空间（type=3）
SELECT type, COUNT(*) AS cnt FROM knowledge GROUP BY type;

SELECT k.id, k.name, k.type, k.user_id, k.state,
       (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id = k.id) AS file_cnt
FROM knowledge k
WHERE k.type = 3
ORDER BY k.id;

SELECT COUNT(*) FROM knowledgefile kf
JOIN knowledge k ON k.id = kf.knowledge_id
WHERE k.type = 3;

-- 成员
SELECT business_type, user_role, status, COUNT(*) AS cnt
FROM space_channel_member
GROUP BY business_type, user_role, status;

-- A-5 权限补偿
SELECT status, COUNT(*) FROM failed_tuple GROUP BY status;

-- A-6 运行中任务（切换前须终态；表名以 A 库为准，不存在则跳过）
-- 解析中文件
SELECT status, COUNT(*) FROM knowledgefile GROUP BY status;

-- ============================================================
-- 两边导出后在线下做的交集（不要在库里跨库 join）
-- ============================================================
-- 1) B.user_name 与 A.user_name 交集 → 仅候选，禁止按名合并
-- 2) B.email / phone 与 A 交集 → 人工确认候选
-- 3) A.external_id 与客户花名册核对；再与 B 本地用户做「员工编码接管」候选
-- 4) A 知识空间 name 与 B knowledge.name 同名 → 不合并，记冲突清单
-- 5) 输出四份清单：用户映射、部门映射、资源/ID 映射、冲突/客户决策

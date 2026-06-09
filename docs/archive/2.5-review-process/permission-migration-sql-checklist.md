# v2.5 权限 / 多租户迁移前后 SQL 校验清单

更新时间：2026-04-23

适用范围：

- `v2_5_0_f001_multi_tenant.py`
- `v2_5_0_f005_role_menu_quota.py`
- `permission/migration/migrate_rbac_to_rebac.py`（F006）
- `v2_5_0_f011_backfill_create_knowledge_web_menu.py`

这份文档不是“跑迁移的 SQL”，而是“迁移前后做数据保全核对的 SQL”。目标是两件事：

1. 迁移前先做基线快照。
2. 迁移后确认没有意外丢数，只出现预期内变化。

## 1. 哪些变化是正常的

先统一预期，不然你看到差异时很难判断是不是事故。

| 表 | 迁移后预期 |
| --- | --- |
| `tenant` | 新增或补齐默认租户，行数可能增加 |
| `user_tenant` | 新增或补齐用户-租户关联，行数可能增加 |
| `role` | 行数应保持不变；可能出现 `role_name-dup-<id>` 去重；新增列 `role_type / department_id / quota_config` |
| `roleaccess` | 行数通常保持不变；如果跑了 F011，`create_knowledge` 菜单记录可能增加 |
| `userrole` | 行数应保持不变 |
| `usergroup` | 行数应保持不变 |
| `groupresource` | 行数应保持不变 |
| `space_channel_member` | 行数应保持不变 |
| `knowledge / knowledgefile / flow / t_gpts_tools / channel` | 行数应保持不变 |
| `failed_tuple` | 理想情况下应为 0；大于 0 说明 F006 写 OpenFGA 有失败补偿待处理 |

结论先记住：

- `F001/F005` 主要是改表结构和补字段，不应该删业务数据。
- `F006` 主要是把旧权限关系写到 OpenFGA，不应该删 MySQL 源表数据。
- `F011` 只会给已有 `knowledge` 菜单权限的角色补 `create_knowledge`，所以 `roleaccess` 可能增行。

## 2. 迁移前先跑的基线 SQL

### 2.1 基础环境确认

```sql
SELECT DATABASE() AS db_name, NOW() AS snapshot_time;
SELECT VERSION() AS mysql_version;
```

### 2.2 核心表行数快照

这组最重要，迁移前后都要跑一次。

```sql
SELECT 'role' AS table_name, COUNT(*) AS row_count FROM role
UNION ALL
SELECT 'roleaccess', COUNT(*) FROM roleaccess
UNION ALL
SELECT 'userrole', COUNT(*) FROM userrole
UNION ALL
SELECT 'usergroup', COUNT(*) FROM usergroup
UNION ALL
SELECT 'groupresource', COUNT(*) FROM groupresource
UNION ALL
SELECT 'space_channel_member', COUNT(*) FROM space_channel_member
UNION ALL
SELECT 'knowledge', COUNT(*) FROM knowledge
UNION ALL
SELECT 'knowledgefile', COUNT(*) FROM knowledgefile
UNION ALL
SELECT 'flow', COUNT(*) FROM flow
UNION ALL
SELECT 't_gpts_tools', COUNT(*) FROM t_gpts_tools
UNION ALL
SELECT 'channel', COUNT(*) FROM channel
UNION ALL
SELECT 'tenant', COUNT(*) FROM tenant
UNION ALL
SELECT 'user_tenant', COUNT(*) FROM user_tenant;
```

如果库里已经有 `failed_tuple`，再补一条：

```sql
SELECT 'failed_tuple' AS table_name, COUNT(*) AS row_count FROM failed_tuple;
```

### 2.3 `role` 专项快照

```sql
SELECT COUNT(*) AS total_roles FROM role;

SELECT tenant_id, role_name, COUNT(*) AS dup_count
FROM role
GROUP BY tenant_id, role_name
HAVING COUNT(*) > 1
ORDER BY dup_count DESC, tenant_id, role_name;

SELECT id, role_name, knowledge_space_file_limit
FROM role
WHERE knowledge_space_file_limit > 0
ORDER BY id;
```

说明：

- 第二条是为了看 F005 前是否已经有重名角色。
- 第三条是为了看后续 `knowledge_space_file_limit -> quota_config` 的迁移基线。

### 2.4 `roleaccess` 专项快照

```sql
SELECT type, COUNT(*) AS row_count
FROM roleaccess
GROUP BY type
ORDER BY type;

SELECT third_id, COUNT(*) AS row_count
FROM roleaccess
WHERE type = 99
GROUP BY third_id
ORDER BY row_count DESC, third_id;

SELECT role_id, COUNT(*) AS non_menu_access_count
FROM roleaccess
WHERE type != 99
GROUP BY role_id
ORDER BY non_menu_access_count DESC, role_id;

SELECT role_id, COUNT(*) AS knowledge_menu_count
FROM roleaccess
WHERE type = 99
  AND third_id = 'knowledge'
GROUP BY role_id
ORDER BY role_id;
```

说明：

- `type = 99` 是 `WEB_MENU`。
- `knowledge` 菜单快照是为了后面核对 F011 的 `create_knowledge` 补数。

### 2.5 RBAC 源表专项快照

```sql
SELECT role_id, COUNT(*) AS user_count
FROM userrole
GROUP BY role_id
ORDER BY user_count DESC, role_id;

SELECT group_id, COUNT(*) AS member_count,
       SUM(CASE WHEN is_group_admin = 1 THEN 1 ELSE 0 END) AS admin_count
FROM usergroup
GROUP BY group_id
ORDER BY member_count DESC, group_id;

SELECT type, COUNT(*) AS row_count
FROM groupresource
GROUP BY type
ORDER BY type;

SELECT business_type, status, user_role, COUNT(*) AS row_count
FROM space_channel_member
GROUP BY business_type, status, user_role
ORDER BY business_type, status, user_role;
```

### 2.6 F006 资源来源表快照

F006 会从这些表推导 owner / parent 关系，所以这些表的行数不应该因为迁移而减少。

```sql
SELECT type, COUNT(*) AS row_count
FROM knowledge
GROUP BY type
ORDER BY type;

SELECT file_type, COUNT(*) AS row_count
FROM knowledgefile
GROUP BY file_type
ORDER BY file_type;

SELECT flow_type, COUNT(*) AS row_count
FROM flow
GROUP BY flow_type
ORDER BY flow_type;

SELECT COUNT(*) AS active_tool_count
FROM t_gpts_tools
WHERE is_delete = 0;

SELECT COUNT(*) AS channel_count
FROM channel;
```

## 3. 迁移后立刻跑的 SQL

### 3.1 表结构核对

```sql
SHOW COLUMNS FROM role LIKE 'role_type';
SHOW COLUMNS FROM role LIKE 'department_id';
SHOW COLUMNS FROM role LIKE 'quota_config';

SHOW COLUMNS FROM roleaccess LIKE 'tenant_id';
SHOW COLUMNS FROM role LIKE 'tenant_id';
SHOW COLUMNS FROM usergroup LIKE 'tenant_id';
SHOW COLUMNS FROM userrole LIKE 'tenant_id';
SHOW COLUMNS FROM knowledge LIKE 'tenant_id';
SHOW COLUMNS FROM flow LIKE 'tenant_id';
```

### 3.2 核心表行数复跑

直接重跑 `2.2` 那组 SQL，和迁移前结果对比。

重点判断：

- `role / userrole / usergroup / groupresource / space_channel_member / knowledge / knowledgefile / flow / t_gpts_tools / channel` 不应无故减少。
- `tenant / user_tenant` 增加是正常的。
- `roleaccess` 如果增加，优先看是不是 `create_knowledge` 补数导致。

### 3.3 `tenant_id` 空值核对

F001 之后，受影响业务表理论上不该再有 `tenant_id IS NULL`。

```sql
SELECT 'role' AS table_name, COUNT(*) AS tenant_id_nulls FROM role WHERE tenant_id IS NULL
UNION ALL
SELECT 'roleaccess', COUNT(*) FROM roleaccess WHERE tenant_id IS NULL
UNION ALL
SELECT 'usergroup', COUNT(*) FROM usergroup WHERE tenant_id IS NULL
UNION ALL
SELECT 'userrole', COUNT(*) FROM userrole WHERE tenant_id IS NULL
UNION ALL
SELECT 'knowledge', COUNT(*) FROM knowledge WHERE tenant_id IS NULL
UNION ALL
SELECT 'knowledgefile', COUNT(*) FROM knowledgefile WHERE tenant_id IS NULL
UNION ALL
SELECT 'flow', COUNT(*) FROM flow WHERE tenant_id IS NULL
UNION ALL
SELECT 't_gpts_tools', COUNT(*) FROM t_gpts_tools WHERE tenant_id IS NULL
UNION ALL
SELECT 'channel', COUNT(*) FROM channel WHERE tenant_id IS NULL;
```

## 4. 重点差异核对 SQL

### 4.1 F005：`role` 去重与配额迁移

```sql
SELECT tenant_id, role_type, role_name, COUNT(*) AS dup_count
FROM role
GROUP BY tenant_id, role_type, role_name
HAVING COUNT(*) > 1
ORDER BY dup_count DESC, tenant_id, role_type, role_name;

SELECT id, role_name, role_type, department_id, quota_config, knowledge_space_file_limit
FROM role
ORDER BY id;

SELECT id, role_name,
       knowledge_space_file_limit,
       JSON_EXTRACT(quota_config, '$.knowledge_space_file') AS quota_kf
FROM role
WHERE knowledge_space_file_limit > 0
ORDER BY id;
```

判定标准：

- 第一条应返回空，说明新唯一约束下没有残留重复。
- 第三条里 `knowledge_space_file_limit > 0` 的记录，应尽量能在 `quota_config.knowledge_space_file` 里看到对应值。

### 4.2 F011：`create_knowledge` 补数核对

```sql
SELECT COUNT(*) AS create_knowledge_count
FROM roleaccess
WHERE type = 99
  AND third_id = 'create_knowledge';

SELECT r.role_id
FROM roleaccess r
WHERE r.type = 99
  AND r.third_id = 'knowledge'
  AND NOT EXISTS (
    SELECT 1
    FROM roleaccess x
    WHERE x.role_id = r.role_id
      AND x.type = 99
      AND x.third_id = 'create_knowledge'
      AND (x.tenant_id <=> r.tenant_id)
  )
ORDER BY r.role_id;
```

判定标准：

- 第二条应返回空；返回非空说明某些拥有 `knowledge` 菜单的角色没有被补上 `create_knowledge`。

### 4.3 F006：源表不能被误删

迁移后重跑下面几组，和迁移前结果对比。

```sql
SELECT type, COUNT(*) AS row_count
FROM roleaccess
GROUP BY type
ORDER BY type;

SELECT role_id, COUNT(*) AS user_count
FROM userrole
GROUP BY role_id
ORDER BY user_count DESC, role_id;

SELECT group_id, COUNT(*) AS member_count,
       SUM(CASE WHEN is_group_admin = 1 THEN 1 ELSE 0 END) AS admin_count
FROM usergroup
GROUP BY group_id
ORDER BY member_count DESC, group_id;

SELECT business_type, status, user_role, COUNT(*) AS row_count
FROM space_channel_member
GROUP BY business_type, status, user_role
ORDER BY business_type, status, user_role;
```

判定标准：

- 这些表是 F006 的“读取源”，不是迁移目标。
- 行数和分布如果下降，优先按事故处理。

### 4.4 F006：失败补偿核对

```sql
SELECT status, COUNT(*) AS row_count
FROM failed_tuple
GROUP BY status
ORDER BY status;

SELECT *
FROM failed_tuple
ORDER BY id DESC
LIMIT 50;
```

判定标准：

- 理想情况下没有失败记录。
- 如果有失败记录，至少要确认是否已重试成功，或者是否只是历史脏数据。

## 5. F001 全量受影响表的 SQL 生成器

如果你真要按“每一张表”逐张核对，直接用下面这段生成 SQL。

### 5.1 生成迁移前/后的全表 `COUNT(*)` 命令

```sql
SELECT CONCAT(
  'SELECT ''', table_name, ''' AS table_name, COUNT(*) AS row_count FROM `', table_name, '`;'
) AS sql_to_run
FROM (
  SELECT 'flow' AS table_name UNION ALL
  SELECT 'flowversion' UNION ALL
  SELECT 'assistant' UNION ALL
  SELECT 'assistantlink' UNION ALL
  SELECT 'tag' UNION ALL
  SELECT 'taglink' UNION ALL
  SELECT 'chatmessage' UNION ALL
  SELECT 'message_session' UNION ALL
  SELECT 't_report' UNION ALL
  SELECT 't_variable_value' UNION ALL
  SELECT 'template' UNION ALL
  SELECT 'group' UNION ALL
  SELECT 'groupresource' UNION ALL
  SELECT 'role' UNION ALL
  SELECT 'roleaccess' UNION ALL
  SELECT 'usergroup' UNION ALL
  SELECT 'evaluation' UNION ALL
  SELECT 'dataset' UNION ALL
  SELECT 'auditlog' UNION ALL
  SELECT 'marktask' UNION ALL
  SELECT 'markrecord' UNION ALL
  SELECT 'markappuser' UNION ALL
  SELECT 'invitecode' UNION ALL
  SELECT 'knowledge' UNION ALL
  SELECT 'knowledgefile' UNION ALL
  SELECT 'qaknowledge' UNION ALL
  SELECT 't_gpts_tools' UNION ALL
  SELECT 't_gpts_tools_type' UNION ALL
  SELECT 'channel' UNION ALL
  SELECT 'channel_info_source' UNION ALL
  SELECT 'channel_article_read' UNION ALL
  SELECT 'share_link' UNION ALL
  SELECT 'inbox_message' UNION ALL
  SELECT 'inbox_message_read' UNION ALL
  SELECT 'finetune' UNION ALL
  SELECT 'presettrain' UNION ALL
  SELECT 'modeldeploy' UNION ALL
  SELECT 'server' UNION ALL
  SELECT 'sftmodel' UNION ALL
  SELECT 'linsight_sop' UNION ALL
  SELECT 'linsight_sop_record' UNION ALL
  SELECT 'linsight_session_version' UNION ALL
  SELECT 'linsight_execute_task' UNION ALL
  SELECT 'llm_server' UNION ALL
  SELECT 'llm_model' UNION ALL
  SELECT 'userrole'
) t
ORDER BY table_name;
```

### 5.2 生成迁移后的全表 `tenant_id` 空值核对命令

```sql
SELECT CONCAT(
  'SELECT ''', table_name, ''' AS table_name, COUNT(*) AS total_rows, ',
  'SUM(CASE WHEN tenant_id IS NULL THEN 1 ELSE 0 END) AS tenant_id_nulls ',
  'FROM `', table_name, '`;'
) AS sql_to_run
FROM (
  SELECT 'flow' AS table_name UNION ALL
  SELECT 'flowversion' UNION ALL
  SELECT 'assistant' UNION ALL
  SELECT 'assistantlink' UNION ALL
  SELECT 'tag' UNION ALL
  SELECT 'taglink' UNION ALL
  SELECT 'chatmessage' UNION ALL
  SELECT 'message_session' UNION ALL
  SELECT 't_report' UNION ALL
  SELECT 't_variable_value' UNION ALL
  SELECT 'template' UNION ALL
  SELECT 'group' UNION ALL
  SELECT 'groupresource' UNION ALL
  SELECT 'role' UNION ALL
  SELECT 'roleaccess' UNION ALL
  SELECT 'usergroup' UNION ALL
  SELECT 'evaluation' UNION ALL
  SELECT 'dataset' UNION ALL
  SELECT 'auditlog' UNION ALL
  SELECT 'marktask' UNION ALL
  SELECT 'markrecord' UNION ALL
  SELECT 'markappuser' UNION ALL
  SELECT 'invitecode' UNION ALL
  SELECT 'knowledge' UNION ALL
  SELECT 'knowledgefile' UNION ALL
  SELECT 'qaknowledge' UNION ALL
  SELECT 't_gpts_tools' UNION ALL
  SELECT 't_gpts_tools_type' UNION ALL
  SELECT 'channel' UNION ALL
  SELECT 'channel_info_source' UNION ALL
  SELECT 'channel_article_read' UNION ALL
  SELECT 'share_link' UNION ALL
  SELECT 'inbox_message' UNION ALL
  SELECT 'inbox_message_read' UNION ALL
  SELECT 'finetune' UNION ALL
  SELECT 'presettrain' UNION ALL
  SELECT 'modeldeploy' UNION ALL
  SELECT 'server' UNION ALL
  SELECT 'sftmodel' UNION ALL
  SELECT 'linsight_sop' UNION ALL
  SELECT 'linsight_sop_record' UNION ALL
  SELECT 'linsight_session_version' UNION ALL
  SELECT 'linsight_execute_task' UNION ALL
  SELECT 'llm_server' UNION ALL
  SELECT 'llm_model' UNION ALL
  SELECT 'userrole'
) t
ORDER BY table_name;
```

## 6. 建议执行顺序

### 迁移前

1. 跑 `2.1 ~ 2.6`。
2. 保存结果到文本或工单。
3. 如果 `role` 已经有大量重名、`roleaccess` 已经存在异常空值，先处理脏数据再迁移。

### 迁移后

1. 跑 `3.1 ~ 3.3`。
2. 跑 `4.1 ~ 4.4`。
3. 如果要逐张表过一遍，再跑第 `5` 节生成的 SQL。

## 7. 这份文档的边界

这份文档当前覆盖的是“这轮权限 / 多租户 / 菜单补数迁移”的数据核对，不覆盖：

- 所有历史 Alembic revision
- OpenFGA 存储层内部表结构差异
- Gateway 独立库

如果你要，我下一步可以再补一版：

1. “可直接复制跑”的 `before.sql` / `after.sql` 两个文件。
2. 带“前后自动 diff”格式的 SQL 报表版。

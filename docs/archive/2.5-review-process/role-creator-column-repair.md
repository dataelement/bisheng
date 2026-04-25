# 角色创建人字段缺失修复说明

更新时间：2026-04-21

适用场景：
- 系统管理 `http://192.168.106.120:3002/sys`
- `角色与权限` -> `角色管理`
- 列表中的“创建人”显示为 `-`
- “仅创建人可编辑/删除”规则未稳定生效

## 1. 问题现象

当前线上问题表现为：

1. 角色管理列表存在“创建人”列，但很多角色显示为 `-`。
2. 后端角色服务依赖 `role.create_user` 字段判断角色创建人。
3. 当前数据库 `role` 表没有 `create_user` 列，导致后端无法稳定返回 `creator_name`。
4. 由于创建人缺失，后续“仅创建人可编辑/删除”的权限约束也存在失真风险。

## 2. 当前排查结论

### 2.1 数据库现状

已在当前开发环境连接的 `bisheng` 库验证，`role` 表不存在 `create_user` 列。

执行结果等价于：

```sql
SHOW COLUMNS FROM role LIKE 'create_user';
```

返回为空。

当前 `role` 表列为：

```text
role_name
role_type
department_id
quota_config
remark
group_id
knowledge_space_file_limit
create_time
update_time
id
tenant_id
```

### 2.2 代码现状

后端代码已经按“如果 `role.create_user` 存在则读写该列”的思路实现：

- [src/backend/bisheng/role/domain/services/role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py)

具体包括：

1. 创建角色后尝试执行：

```sql
UPDATE role SET create_user = :uid WHERE id = :rid
```

2. 列表接口尝试执行：

```sql
SELECT id, create_user FROM role WHERE id IN (...)
```

### 2.3 迁移现状

当前仓库 `alembic` 版本目录中没有可执行的正式迁移源码来新增 `role.create_user`。

已确认：

- 正式迁移目录：`src/backend/bisheng/core/database/alembic/versions/`
- 存在一个残留缓存文件：
  - `src/backend/bisheng/core/database/alembic/versions/__pycache__/v2_5_1_f018_role_creator.cpython-310.pyc`
- 但不存在对应的 `.py` revision 源码文件。

这意味着：

1. 仅靠当前代码重启服务，不能保证该列会自动迁移出来。
2. 即使启动时执行 `alembic upgrade head`，也不会补出这列。

## 3. 风险说明

当前后端启动脚本会在 API 启动前执行：

```bash
alembic upgrade head || echo "WARNING: alembic migration failed, continuing startup..."
```

文件位置：

- [src/backend/entrypoint.sh](/Users/zhou/Code/bisheng/src/backend/entrypoint.sh)

这意味着：

1. 迁移失败可能被吞掉。
2. 服务仍然会继续启动。
3. 不能通过“服务能启动”反推数据库迁移成功。

因此，明天修复时不要只做重启，必须手工校验表结构。

## 4. 明天推荐修复方案

推荐分为两步：

1. 运维先做数据库热修，补齐 `role.create_user` 列。
2. 开发补正式 alembic migration 和兜底逻辑后，再发版固化。

## 5. 运维执行步骤

### 5.1 执行前检查

先在目标环境数据库执行：

```sql
SHOW COLUMNS FROM role LIKE 'create_user';
```

如果已有结果，则不要重复加列。

### 5.2 热修 SQL

如果缺列，执行：

```sql
ALTER TABLE role
ADD COLUMN create_user INT NULL COMMENT 'Role creator user ID';
```

如果需要显式指定位置，可用：

```sql
ALTER TABLE role
ADD COLUMN create_user INT NULL COMMENT 'Role creator user ID'
AFTER tenant_id;
```

说明：

1. 字段允许 `NULL`，兼容历史角色。
2. 当前代码已经会在新建角色后尝试写入 `create_user`，所以补列后，新创建角色即可开始落创建人。

### 5.3 历史数据回填

如果要尽量恢复历史角色的创建人，可按 `audit_log` 做一次最佳努力回填。

建议先预览：

```sql
SELECT
  CAST(al.object_id AS UNSIGNED) AS role_id,
  MIN(al.create_time) AS first_create_time,
  SUBSTRING_INDEX(
    GROUP_CONCAT(al.operator_id ORDER BY al.create_time ASC),
    ',',
    1
  ) AS creator_id
FROM audit_log al
WHERE al.system_id = 'system'
  AND al.event_type = 'create_role'
  AND al.object_type = 'role_conf'
  AND al.object_id REGEXP '^[0-9]+$'
GROUP BY CAST(al.object_id AS UNSIGNED)
ORDER BY role_id;
```

确认无误后执行回填：

```sql
UPDATE role r
JOIN (
  SELECT
    CAST(al.object_id AS UNSIGNED) AS role_id,
    CAST(
      SUBSTRING_INDEX(
        GROUP_CONCAT(al.operator_id ORDER BY al.create_time ASC),
        ',',
        1
      ) AS UNSIGNED
    ) AS creator_id
  FROM audit_log al
  WHERE al.system_id = 'system'
    AND al.event_type = 'create_role'
    AND al.object_type = 'role_conf'
    AND al.object_id REGEXP '^[0-9]+$'
  GROUP BY CAST(al.object_id AS UNSIGNED)
) s ON s.role_id = r.id
SET r.create_user = s.creator_id
WHERE r.create_user IS NULL;
```

注意：

1. 该回填依赖 `audit_log` 历史数据完整。
2. 通过新 `/api/v1/roles` 创建、但未写审计的角色，可能仍然回填不到。
3. 回填不到的角色，`create_user` 仍会保持 `NULL`。

## 6. 执行后验证

### 6.1 数据库验证

执行：

```sql
SHOW COLUMNS FROM role LIKE 'create_user';
```

以及：

```sql
SELECT id, role_name, create_user
FROM role
ORDER BY id DESC
LIMIT 20;
```

### 6.2 应用验证

1. 登录系统管理页：`/sys`
2. 进入 `角色与权限` -> `角色管理`
3. 新建一个测试角色
4. 刷新列表
5. 确认该角色“创建人”不再显示为 `-`
6. 用非创建人账号验证“编辑/删除”是否被拦截

## 7. 后续代码侧补丁

数据库补列只能解决一半问题，后续仍需代码补丁，建议同一次或下一次发版完成：

1. 补正式 alembic migration 文件，避免新环境再次缺列。
2. 新 `/api/v1/roles` 接口补 `create_role/update_role/delete_role` 审计日志。
3. 当 `create_user` 为空时，后端不应退回到宽松的旧权限逻辑，应默认只读。
4. 列表接口可增加 `audit_log` 兜底查创建人，兼容历史脏数据。

## 8. 回滚方案

如果仅添加了列且未回填，一般无需回滚。

如果确需回滚：

```sql
ALTER TABLE role DROP COLUMN create_user;
```

不建议在业务高峰期回滚，因为：

1. 当前代码已经开始尝试读写该列。
2. 回滚后会重新回到“创建人无法稳定识别”的状态。

## 9. 明天建议执行顺序

建议按以下顺序处理：

1. 运维先在目标库确认 `role.create_user` 是否缺失。
2. 若缺失，先执行 `ALTER TABLE` 补列。
3. 视窗口时间决定是否执行历史回填。
4. 验证新建角色是否能写入创建人。
5. 待开发补齐正式 migration 与代码兜底后，再发版固化。

## 10. 结论

当前问题的根因不是前端缺列，而是：

1. 数据库 `role` 表没有 `create_user` 字段。
2. 仓库缺少正式 alembic migration 源码。
3. 启动脚本对迁移失败不阻断，容易造成“服务正常但表结构不完整”的假象。

明天运维在场时，优先做数据库补列和验证；后续再由开发补齐代码与正式迁移。

# Tasks: 权限数据迁移

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | SDD Review 通过 |
| tasks.md | ✅ 已拆解 | SDD Review 通过 |
| 实现 | ✅ 已完成 | 8 / 8 完成 |

---

## 任务列表

### T1: 迁移脚本骨架 + CLI 入口 + Checkpoint 机制

**类型**: 基础设施
**依赖**: 无
**目标**: 创建 `RBACToReBACMigrator` 类骨架，实现 CLI 参数解析、checkpoint 持久化、批量写入基础设施。

**文件**:
- 新建: `src/backend/bisheng/permission/migration/__init__.py`
- 新建: `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`

**AC 覆盖**: AC-09, AC-10, AC-11

**验证**:
- [x] `python -m bisheng.permission.migration.migrate_rbac_to_rebac --help` 输出帮助
- [x] `python -m bisheng.permission.migration.migrate_rbac_to_rebac --dry-run` 可运行（各步骤为空壳）
- [x] checkpoint 文件正确创建、读取、恢复
- [x] `--step 3` 正确跳过 step 1-2

**实现要点**:
- `RBACToReBACMigrator` 类含 `__init__`, `run()`, `_load_checkpoint()`, `_save_checkpoint()`
- `_collect()` 累积元组到 `_buffer: list[TupleOperation]`
- `_flush()` 去重 → 分批 100 → `FGAClient.write_tuples()` → 已存在则跳过 → 批量失败降级逐条
- `_dedup_tuples()` dict keyed by (user, object) 保留最高 relation（`RELATION_PRIORITY = {owner:4, manager:3, editor:2, viewer:1}`）
- CLI: `argparse` 解析 `--dry-run`, `--verify`, `--step N`
- `MigrationStats` dataclass 统计各步骤写入数
- checkpoint JSON: `{"completed_step": N, "timestamp": "...", "stats": {...}}`

**估时**: 2h

---

### T2: 测试框架 + Step 1/2 测试用例

**类型**: 后端测试
**依赖**: T1
**目标**: 搭建迁移脚本测试 fixture，编写 Step 1（超管）和 Step 2（用户组成员）的测试用例。

**文件**:
- 新建: `test/test_f006_permission_migration.py`

**AC 覆盖**: AC-01, AC-02, AC-09

**测试降级说明**: 迁移脚本是单文件单类工具（非标准 DDD Domain Service），测试 fixture 依赖 T1 骨架完成后才能构造 mock。因此 T2 在 T1 之后但在 Step 1/2 实现之前执行。测试用例先写为预期断言（red），T3 实现后变绿。

**验证**:
- [ ] pytest fixture: mock FGAClient（write_tuples 记录调用参数）
- [ ] pytest fixture: mock DB session（预填充 user_role、user_group 测试数据）
- [ ] test_step1_super_admin: AdminRole 用户 → system:global super_admin 元组
- [ ] test_step2_user_group_membership: is_group_admin=True → admin, False → member
- [ ] test_checkpoint_save_load: 保存后加载恢复正确
- [ ] test_idempotent_rerun: 运行两次无报错

**估时**: 1.5h

---

### T3: Step 1 — 超管迁移 + Step 2 — 用户组成员迁移

**类型**: 后端 Domain
**依赖**: T1, T2
**目标**: 实现 `step1_super_admin()` 和 `step2_user_group_membership()`，使 T2 测试通过。

**文件**:
- 修改: `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`

**AC 覆盖**: AC-01, AC-02

**验证**:
- [ ] T2 中的 test_step1/test_step2 测试全部通过
- [ ] `--dry-run` 输出 Step 1/2 统计
- [ ] AdminRole 用户写入 `(system:global, super_admin, user:{id})`
- [ ] user_group 正确区分 member/admin
- [ ] 默认用户组（id=2）的成员也被迁移

**实现要点**:
- Step 1: `UserRoleDao.get_admins_user()` → 生成 TupleOperation
- Step 2: 全量查 `UserGroup` → is_group_admin 判断 → member 或 admin
- 两步共用 `_collect()` + `_flush()` 管道

**估时**: 1h

---

### T4: Step 3 测试用例 + 实现 — role_access 展开 + 去重优化

**类型**: 后端 Domain（测试先行）
**依赖**: T3
**目标**: 先编写 Step 3 测试用例，再实现 `step3_role_access()`。

**文件**:
- 修改: `test/test_f006_permission_migration.py`（新增测试）
- 修改: `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`（实现 step3）

**AC 覆盖**: AC-03

**验证**:
- [ ] test_step3_skip_web_menu: WEB_MENU(99) 记录被跳过
- [ ] test_step3_skip_admin_role: AdminRole(1) 的 role_access 记录被跳过
- [ ] test_step3_access_type_mapping: 每种 AccessType 正确映射到 (object_type, relation)
- [ ] test_step3_expand_to_users: 展开后每用户一条元组
- [ ] test_step3_dedup_read_write: 同用户同资源有 READ+WRITE 时只写 editor
- [ ] test_step3_dedup_manager_editor: 同用户同资源有 manager+editor 时只写 manager
- [ ] `--dry-run` 输出 raw 数量和去重后数量

**实现要点**:
- 定义 `ACCESS_TYPE_MAPPING` 常量
- 构建 `role_id → set[user_id]` 映射（全量查 UserRole，排除 role_id=1）
- 全量查 RoleAccess (type != 99)，按映射展开
- `_dedup_tuples()` 处理 (user, object) 冲突

**估时**: 2.5h

---

### T5: Step 4/5 测试用例 + 实现 — 空间/频道成员 + 资源 ownership

**类型**: 后端 Domain（测试先行）
**依赖**: T4
**目标**: 先编写 Step 4/5 测试用例，再实现 `step4_space_channel_members()` 和 `step5_resource_owners()`。

**文件**:
- 修改: `test/test_f006_permission_migration.py`（新增测试）
- 修改: `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`（实现 step4/5）

**AC 覆盖**: AC-04, AC-05

**验证**:
- [ ] test_step4_active_only: 仅迁移 ACTIVE 状态的 space_channel_member
- [ ] test_step4_role_mapping: creator→owner, admin→manager, member→viewer
- [ ] test_step4_type_mapping: space→knowledge_space, channel→channel
- [ ] test_step5_flow_type_filter: flow_type=5→assistant, 10→workflow, 其他跳过
- [ ] test_step5_knowledge_all_types: 所有类型 Knowledge 均迁移
- [ ] test_step5_gpts_tools_skip_deleted: is_delete=1 跳过
- [ ] test_step5_dashboard_not_exist: Dashboard 表不存在时 WARNING 跳过
- [ ] test_step4_step5_dedup: creator owner 不重复写入

**实现要点**:
- Step 4: 全量查 SpaceChannelMember(status=ACTIVE)，角色映射 + 类型映射
- Step 5: 分别查询 Flow/Knowledge/GptsTools/Channel + raw SQL 查 dashboard
- Dashboard raw SQL: `SELECT id, user_id FROM dashboard`，包裹在 try-except 中
- FLOW_TYPE_MAPPING、SCM_ROLE_MAPPING 常量
- 跨步骤去重：Step 5 在 `_global_dedup` dict 中注册 owner，Step 3/4 生成元组时检查

**估时**: 3h

---

### T6: Step 6 测试用例 + 实现 — 文件夹层级迁移

**类型**: 后端 Domain（测试先行）
**依赖**: T5
**目标**: 先编写 Step 6 测试用例，再实现 `step6_folder_hierarchy()`。

**文件**:
- 修改: `test/test_f006_permission_migration.py`（新增测试）
- 修改: `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`（实现 step6）

**AC 覆盖**: AC-06

**验证**:
- [ ] test_step6_folder_root: file_type=0 + 空 path → (folder:{id}, parent, knowledge_space:{kid})
- [ ] test_step6_folder_nested: file_type=0 + path="/42" → (folder:{id}, parent, folder:42)
- [ ] test_step6_folder_deep: file_type=0 + path="/42/78" → (folder:{id}, parent, folder:78)
- [ ] test_step6_file_root: file_type=1 + 空 path → (knowledge_file:{id}, parent, knowledge_space:{kid})
- [ ] test_step6_file_in_folder: file_type=1 + path="/42" → (knowledge_file:{id}, parent, folder:42)
- [ ] test_step6_invalid_path: 无效 path segment → WARNING 跳过
- [ ] `--dry-run` 输出 folder/knowledge_file 分布

**实现要点**:
- `_resolve_parent()` 方法：split('/') → 取最后非空 segment → 返回 (parent_type, parent_id)
- 全量查 KnowledgeFile → 对每条记录生成一条 parent 元组
- parent 元组不需要去重（每个文件/文件夹只有一个 parent）

**估时**: 2h

---

### T7: verify 模式 + init_data 集成 + dry-run 美化输出

**类型**: 后端 Domain
**依赖**: T6
**目标**: 实现 `verify_all()` 对比逻辑、`init_default_data()` 集成调用、dry-run 统计输出格式。

**文件**:
- 修改: `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`（verify + dry-run 输出）
- 修改: `src/backend/bisheng/common/init_data.py`（添加自动迁移调用）

**AC 覆盖**: AC-07, AC-08, AC-11

**跨模块影响**: 修改 `common/init_data.py`（全局共享文件，应用启动 lifespan 调用），仅在末尾添加一个异步函数调用，不影响其他初始化逻辑。

**验证**:
- [ ] `--dry-run` 输出格式与 spec §6.3 一致
- [ ] `--verify` 对比报告格式正确
- [ ] 回归数 > 0 时退出码非零
- [ ] init_data 集成：首次启动自动执行迁移
- [ ] init_data 集成：Redis key 标记后不再重复执行
- [ ] init_data 集成：SETNX 锁防止多进程并发（TTL=3600s）

**实现要点**:
- `verify_all()`: 采样用户（排除 AdminRole）+ 采样各类资源（每类 ≤100）
- 旧系统检查：`RoleAccessDao.judge_role_access()` + user_id owner check
- 新系统检查：`PermissionService.check(user_id, 'can_read', ...)`
- `VerifyReport` dataclass: total, match, regression, expansion
- `_migrate_rbac_to_rebac_if_needed()` 添加到 init_data.py

**估时**: 2.5h

---

### T8: 集成测试 + E2E 验证

**类型**: 后端测试
**依赖**: T7
**目标**: 编写全流程集成测试，验证完整迁移管道。

**文件**:
- 修改: `test/test_f006_permission_migration.py`（新增集成测试）

**AC 覆盖**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11

**验证**:
- [ ] test_full_dry_run: 全流程 dry-run 验证统计数据
- [ ] test_full_migration: 全流程迁移（mock FGA）验证元组完整性
- [ ] test_idempotent_full_run: 运行两次，第二次所有步骤 checkpoint 跳过
- [ ] test_checkpoint_resume: 中断后从断点恢复
- [ ] test_verify_mode: verify 模式对比逻辑正确
- [ ] test_init_data_integration: init_data 集成首次运行 + 跳过

**实现要点**:
- pytest fixtures: 综合场景测试数据（多角色、多资源、多成员关系）
- 验证写入的 TupleOperation 列表的完整性和正确性
- 验证去重逻辑在全流程中正确工作

**估时**: 2h

---

## 手动验证清单

> 在远程服务器 192.168.106.114 上执行

- [ ] 准备 v2.4 测试数据：创建多角色、多用户组、多资源（知识库/工作流/助手/工具/频道）
- [ ] 运行 `--dry-run`，确认统计数据合理
- [ ] 运行默认模式，确认迁移完成无错误
- [ ] 运行 `--verify`，确认回归数为 0
- [ ] 重跑迁移，确认幂等（无报错、无重复数据）
- [ ] 重启应用，确认 init_data 不重复执行（日志检查）
- [ ] 用普通用户登录，确认资源可见性与迁移前一致
- [ ] 用管理员登录，确认全权限
- [ ] 检查 FailedTuple 表无 pending 记录

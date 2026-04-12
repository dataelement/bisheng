# Feature: 权限数据迁移

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 技术方案 §6 迁移策略](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20技术方案.md)、[2.5 PRD §3.4 版本升级数据迁移逻辑](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 迁移脚本 `RBACToReBACMigrator`（6 个步骤）：
  - Step 1: 超管迁移（`user_role` role_id=1 → `system:global` super_admin）
  - Step 2: 用户组成员（`user_group` → `user_group:{gid}` member/admin）
  - Step 3: role_access 展开（非 WEB_MENU → 每用户资源元组，含去重优化）
  - Step 4: 空间/频道成员（`space_channel_member` ACTIVE → owner/manager/viewer）
  - Step 5: 资源 ownership（各资源表 `user_id` → owner）
  - Step 6: 文件夹层级（`knowledge_file` → parent 元组）
- 三种运行模式：默认（执行）、`--dry-run`（统计不写入）、`--verify`（对比新旧系统）
- 双模式入口：独立 CLI 脚本 + init_default_data() 启动时自动调用
- 幂等执行（捕获 "already exists"）+ 断点续传（每步 checkpoint）
- 批量写入（100 条/批）+ 失败降级逐条 + FailedTuple 补偿

**OUT**:
- group_resource → **不迁移，直接废弃**（已与产品确认）
- 旧表废弃标记（role_access 非 WEB_MENU 记录、group_resource、space_channel_member 的 deprecated 标记）→ 推迟到上线稳定后清理，F006 仅做数据迁移不修改旧表
- 权限检查代码本身 → F004-rebac-core（已完成）
- 资源模块适配 → F008-resource-rebac-adaptation
- 前端变更 → 无（纯后端数据迁移）

**关键决策**:
- AD-M01: 一步到位，不搞双写过渡期（迁移脚本保证零丢失）
- AD-M02: group_resource 不迁移（旧系统中不参与 access_check，迁移会导致权限扩大）
- AD-M03: Dashboard 表通过 raw SQL 查询（源码为编译 .pyc，无法直接 import ORM）

**关联不变量**: INV-4, INV-10

---

## 1. 概述与用户故事

F006 是 v2.4 → v2.5 升级的关键桥梁。它将旧 RBAC 权限数据（role_access、space_channel_member、资源 ownership、文件夹层级）一次性迁移到 OpenFGA，确保社区存量用户升级后权限零丢失。迁移完成后，旧表的资源授权记录标记为废弃，权限检查完全由 ReBAC 接管。

### 用户故事

**US-01 运维工程师**：作为负责升级的运维工程师，我期望 v2.4→v2.5 升级时权限数据自动迁移，无需手动操作 OpenFGA，升级后用户权限与升级前完全一致。

**US-02 谨慎型运维**：作为需要预先验证的运维工程师，我期望能先用 `--dry-run` 预览迁移统计（元组数量、各类型分布），确认无误后再正式执行迁移。

**US-03 迁移验证者**：作为负责验证的工程师，我期望用 `--verify` 对比新旧系统的权限判定结果，确认回归数为零后才放心上线。

**US-04 中断恢复**：作为运维工程师，如果迁移过程中发生网络中断或 OpenFGA 宕机，我期望能从断点恢复，而不需要从头重跑。

**US-05 二次执行**：作为运维工程师，如果对迁移结果不放心想重跑一次，我期望脚本是幂等的——重跑不会产生重复数据或报错。

---

## 2. 验收标准

### AC-01: Step 1 — 超管迁移

- [ ] 所有 `user_role` 中 `role_id == AdminRole(1)` 的用户 → 写入 `(system:global, super_admin, user:{user_id})`
- [ ] AdminRole 用户同时拥有超管元组和原有角色（不互斥）

### AC-02: Step 2 — 用户组成员迁移

- [ ] `user_group` 中 `is_group_admin == False` → `(user_group:{group_id}, member, user:{user_id})`
- [ ] `user_group` 中 `is_group_admin == True` → `(user_group:{group_id}, admin, user:{user_id})`
- [ ] 默认用户组（id=2）的成员也被迁移

### AC-03: Step 3 — role_access 展开为用户级元组

- [ ] `role_access` 中 `type == WEB_MENU(99)` 的记录 → 跳过不迁移
- [ ] `role_access` 中 `role_id == AdminRole(1)` 的记录 → 跳过（admin 在 Step 1 已覆盖）
- [ ] 其余 role_access 记录按 AccessType → (object_type, relation) 映射表展开
- [ ] 展开逻辑：对每条 role_access，查 `user_role` 获取所有持有该角色的用户，为每个用户写入直接元组
- [ ] **去重优化**：同一 `(user_id, object_type, resource_id)` 有多个 relation 时，只保留最高级（owner > editor > viewer）

### AC-04: Step 4 — 空间/频道成员迁移

- [ ] 仅迁移 `status == 'ACTIVE'` 的记录（PENDING/REJECTED 跳过）
- [ ] `user_role` 映射：creator → owner, admin → manager, member → viewer
- [ ] `business_type` 映射：space → knowledge_space, channel → channel
- [ ] 与 Step 5 的 owner 元组去重（creator 的 owner 不重复写入）

### AC-05: Step 5 — 资源 ownership 迁移

- [ ] Flow 表：`flow_type == ASSISTANT(5)` → `(assistant:{id}, owner, user:{user_id})`
- [ ] Flow 表：`flow_type == WORKFLOW(10)` → `(workflow:{id}, owner, user:{user_id})`
- [ ] Flow 表：其他 flow_type（15/20/25/30）→ 跳过
- [ ] Knowledge 表：所有记录（含 NORMAL/QA/PRIVATE/SPACE 全部类型）→ `(knowledge_space:{id}, owner, user:{user_id})`
- [ ] GptsTools 表：`is_delete == 0` → `(tool:{id}, owner, user:{user_id})`
- [ ] Channel 表：所有记录 → `(channel:{id}, owner, user:{user_id})`
- [ ] Dashboard 表：通过 raw SQL `SELECT id, user_id FROM dashboard` → `(dashboard:{id}, owner, user:{user_id})`
- [ ] Dashboard 表不存在时静默跳过（WARNING 日志），兼容无 Dashboard 的部署
- [ ] 与 Step 3/4 已写入的元组去重（owner 已存在则跳过 viewer/editor）

### AC-06: Step 6 — 文件夹层级迁移

- [ ] `knowledge_file` 中 `file_type == 0`（文件夹）且 `file_level_path` 为空/None → `(folder:{id}, parent, knowledge_space:{knowledge_id})`
- [ ] `knowledge_file` 中 `file_type == 0`（文件夹）且 `file_level_path` 非空 → `(folder:{id}, parent, folder:{last_segment})`
- [ ] `knowledge_file` 中 `file_type == 1`（文件）且 `file_level_path` 为空/None → `(knowledge_file:{id}, parent, knowledge_space:{knowledge_id})`
- [ ] `knowledge_file` 中 `file_type == 1`（文件）且 `file_level_path` 非空 → `(knowledge_file:{id}, parent, folder:{last_segment})`
- [ ] `file_level_path` 解析逻辑：按 `/` 分割取最后一个非空 segment 作为 parent folder id

### AC-07: dry-run 模式

- [ ] `--dry-run` 不写入任何 OpenFGA 元组
- [ ] 输出每步的统计：待写入元组数、去重后数量
- [ ] 输出汇总：各 object_type 的分布、各 relation 的分布、总元组数

### AC-08: verify 模式

- [ ] `--verify` 采样所有非管理员用户
- [ ] 对每类资源采样（每类最多 100 个）
- [ ] 对每个 (user, resource) 组合，分别用旧系统和新系统检查 can_read 权限
- [ ] 输出报告：总检查数、匹配数、回归数（旧YES新NO，**必须为 0**）、扩展数（旧NO新YES，可接受）
- [ ] 回归数 > 0 时退出码非零，脚本返回失败

### AC-09: 幂等性与断点续传

- [ ] 重复写入已存在的元组不报错（捕获 "already exists"，视为成功）
- [ ] 每步完成后写入 checkpoint 文件（JSON 格式，含 completed_step + timestamp + stats）
- [ ] 中断后重跑自动跳过已完成的步骤
- [ ] `--step N` 参数支持手动指定从第 N 步开始

### AC-10: 批量写入与错误处理

- [ ] 每批最多 100 条元组，调用 `FGAClient.write_tuples()`
- [ ] 批量失败时降级为逐条写入
- [ ] 单条写入仍失败时记入 `failed_tuple` 补偿表（INV-4）
- [ ] OpenFGA 完全不可达时抛出异常，不写 checkpoint，下次重启重试

### AC-11: 双模式运行

- [ ] 独立 CLI：`python -m bisheng.permission.migration.migrate_rbac_to_rebac [--dry-run] [--verify] [--step N]`
- [ ] 启动集成：`init_default_data()` 末尾调用 `_migrate_rbac_to_rebac_if_needed()`
- [ ] 启动集成通过 Redis key `migration:f006:completed` 判断是否已完成，已完成则跳过
- [ ] 迁移成功后设置 Redis key，值包含完成时间和统计信息

---

## 3. 边界情况

| ID | 场景 | 预期行为 |
|----|------|---------|
| EC-01 | OpenFGA 服务不可达 | 抛出异常，不写 checkpoint，应用启动时下次重试 |
| EC-02 | role_access 引用了已删除的资源 | 仍写入 OpenFGA 元组（OpenFGA 不验证资源是否存在）；PermissionService.check() 对不存在的资源返回 False 无副作用 |
| EC-03 | 同一用户通过多个角色获得同一资源的 READ 和 WRITE | 去重优化只写入 editor（高级包含低级） |
| EC-04 | 用户既是资源 owner（Step 5）又通过 role_access（Step 3）获得 viewer | 去重优化只保留 owner |
| EC-05 | space_channel_member 中 creator 与资源表 user_id 不一致 | 两个 owner 元组都写入（OpenFGA 支持多 owner，check 取并集） |
| EC-06 | Dashboard 表不存在（社区版可能无此模块） | Step 5 中 raw SQL 捕获异常，跳过 Dashboard 迁移，日志 WARNING |
| EC-07 | 超大规模部署（10万+元组） | 每批 100 条 + checkpoint 确保可中断恢复；启动集成模式下迁移阻塞应用就绪（lifespan 内同步执行），大规模部署建议先用 CLI `--dry-run` 评估再手动执行 |
| EC-08 | file_level_path 包含无效 segment（非数字） | 跳过该记录，日志 WARNING，不影响其他记录 |
| EC-09 | 多进程并发启动触发迁移 | Redis SETNX 锁保证只有一个进程执行迁移 |
| EC-10 | 迁移完成后回滚到 v2.4 | OpenFGA 中的元组不影响旧系统运行（旧系统不查 OpenFGA）；恢复旧代码即可 |

---

## 4. 架构决策

| ID | 决策 | 理由 | 替代方案 |
|----|------|------|---------|
| AD-M01 | 一步到位迁移，不设双写过渡期 | PRD Review 决策 #2；双写增加代码复杂度和运维负担；迁移脚本 + verify 模式足以保证零丢失 | 双写 1-2 周后切换 |
| AD-M02 | group_resource 不迁移到 OpenFGA | 旧系统中 group_resource 不参与 access_check（仅管理页展示/过滤）；直接转为 viewer 会导致权限扩大 | 全部转为 viewer 元组 |
| AD-M03 | Dashboard 用 raw SQL 查询 | telemetry_search 模块只有编译 .pyc，ORM 模型无法 import；raw SQL 最可靠 | 重写 Dashboard ORM |
| AD-M04 | 迁移使用独立 FGAClient（超时 30s） | 批量写入耗时长，默认 5s 超时不够；独立实例不影响线上请求 | 复用全局 FGAClient |
| AD-M05 | Checkpoint 使用本地 JSON 文件 | 不依赖 Redis（迁移时 Redis 可能未初始化）；文件可在容器重启间持久化（需 volume） | Redis key 存储 |
| AD-M06 | 去重在内存中完成 | 去重逻辑简单（dict keyed by (user, object_type, resource_id)，取最高 relation）；内存占用可控（单实例部署） | OpenFGA 端去重（逐条 check before write） |

---

## 5. 数据库 & Domain 模型

### 5.1 无新增表

F006 不新增数据库表。所有基础设施（FailedTuple、OpenFGA 授权模型等）已在 F004 中建立。

### 5.2 源数据表（只读）

| 表名 | ORM 位置 | 关键字段 | 步骤 |
|------|---------|---------|------|
| `user_role` | `user/domain/models/user_role.py` | user_id, role_id | 1, 3 |
| `user_group` | `database/models/user_group.py` | user_id, group_id, is_group_admin | 2 |
| `role_access` | `database/models/role_access.py` | role_id, third_id, type | 3 |
| `space_channel_member` | `common/models/space_channel_member.py` | business_id, business_type, user_id, user_role, status | 4 |
| `flow` | `database/models/flow.py` | id, user_id, flow_type | 5 |
| `knowledge` | `knowledge/domain/models/knowledge.py` | id, user_id | 5 |
| `t_gpts_tools` | `tool/domain/models/gpts_tools.py` | id, user_id, is_delete | 5 |
| `channel` | `channel/domain/models/channel.py` | id, user_id | 5 |
| `dashboard` | (无 ORM，raw SQL) | id, user_id | 5 |
| `knowledge_file` | `knowledge/domain/models/knowledge_file.py` | id, knowledge_id, file_type, file_level_path | 6 |

### 5.3 映射常量

#### AccessType → OpenFGA 映射

```python
ACCESS_TYPE_MAPPING: dict[int, tuple[str, str]] = {
    # AccessType.value → (object_type, relation)
    1:  ('knowledge_space', 'viewer'),   # KNOWLEDGE
    3:  ('knowledge_space', 'editor'),   # KNOWLEDGE_WRITE
    5:  ('assistant', 'viewer'),          # ASSISTANT_READ
    6:  ('assistant', 'editor'),          # ASSISTANT_WRITE
    7:  ('tool', 'viewer'),               # GPTS_TOOL_READ
    8:  ('tool', 'editor'),               # GPTS_TOOL_WRITE
    9:  ('workflow', 'viewer'),            # WORKFLOW
    10: ('workflow', 'editor'),            # WORKFLOW_WRITE
    11: ('dashboard', 'viewer'),           # DASHBOARD
    12: ('dashboard', 'editor'),           # DASHBOARD_WRITE
    # 99: WEB_MENU → 不迁移
}
```

#### FlowType → OpenFGA object_type 映射

```python
FLOW_TYPE_MAPPING: dict[int, str] = {
    5:  'assistant',    # ASSISTANT
    10: 'workflow',     # WORKFLOW
    # 15, 20, 25, 30 → 不迁移
}
```

#### 权限级别优先级（去重用）

```python
RELATION_PRIORITY: dict[str, int] = {
    'owner': 4,
    'manager': 3,
    'editor': 2,
    'viewer': 1,
}
```

#### space_channel_member 角色映射

```python
SCM_ROLE_MAPPING: dict[str, str] = {
    'creator': 'owner',
    'admin': 'manager',
    'member': 'viewer',
}
```

---

## 6. API 契约

### 6.1 CLI 接口

```bash
# 默认模式：执行迁移
python -m bisheng.permission.migration.migrate_rbac_to_rebac

# 预览模式：只统计不写入
python -m bisheng.permission.migration.migrate_rbac_to_rebac --dry-run

# 验证模式：对比新旧系统
python -m bisheng.permission.migration.migrate_rbac_to_rebac --verify

# 断点续传：从第 N 步开始
python -m bisheng.permission.migration.migrate_rbac_to_rebac --step 3

# 组合使用
python -m bisheng.permission.migration.migrate_rbac_to_rebac --dry-run --step 3
```

### 6.2 无 HTTP API

F006 是一次性数据迁移，不暴露 HTTP API。权限相关 API 已在 F004 中定义。

### 6.3 输出格式

#### dry-run 输出

```
=== F006 Permission Migration (DRY-RUN) ===

Step 1: Super Admin
  Tuples to write: 3

Step 2: User Group Membership
  Tuples to write: 156

Step 3: Role Access Expansion
  Raw tuples: 2,340
  After dedup: 1,876  (removed 464 lower-level duplicates)

Step 4: Space/Channel Members
  Tuples to write: 89

Step 5: Resource Owners
  knowledge_space: 45
  workflow: 120
  assistant: 80
  tool: 35
  channel: 12
  dashboard: 8
  Total: 300

Step 6: Folder Hierarchy
  folder parent tuples: 230
  knowledge_file parent tuples: 1,450
  Total: 1,680

=== Summary ===
Total unique tuples: 4,104
By object_type: knowledge_space=134, workflow=320, assistant=280, ...
By relation: owner=300, editor=876, viewer=1,000, member=156, ...
```

#### verify 输出

```
=== F006 Permission Verification ===

Sampling: 50 users × 100 resources per type = 5,000 checks

Results:
  Total checks:          5,000
  Match (both agree):    4,997
  Regression (old=YES, new=NO): 0     ← MUST be 0
  Expansion (old=NO, new=YES):  3     ← acceptable

Exit code: 0 (PASS)
```

---

## 7. Service 层逻辑

### 7.1 RBACToReBACMigrator

```
RBACToReBACMigrator
  __init__(dry_run=False, verify_only=False, start_step=1, checkpoint_dir=None)
  
  # === 编排 ===
  async run() -> MigrationStats
      加载 checkpoint → for step in [1..6]: if step > checkpoint → 执行 → 保存 checkpoint
  
  # === 6 个迁移步骤 ===
  async step1_super_admin() -> int
      UserRoleDao.get_admins_user() → 生成 (system:global, super_admin, user:{id}) → _flush()
  
  async step2_user_group_membership() -> int
      全量查 UserGroup → is_group_admin ? admin : member → (user_group:{gid}, rel, user:{uid})
  
  async step3_role_access() -> int
      全量查 RoleAccess (type != 99) → 跳过 role_id=1
      构建 role_id → [user_id] 映射（from UserRole）
      展开每条 role_access → 每用户一条元组
      _dedup_tuples() → _flush()
  
  async step4_space_channel_members() -> int
      全量查 SpaceChannelMember (status=ACTIVE)
      role_map: creator→owner, admin→manager, member→viewer
      type_map: space→knowledge_space, channel→channel
      → _flush()
  
  async step5_resource_owners() -> int
      _migrate_flow_owners()           # FlowType=5→assistant, 10→workflow
      _migrate_knowledge_owners()      # Knowledge → knowledge_space
      _migrate_tool_owners()           # GptsTools (is_delete=0) → tool
      _migrate_channel_owners()        # Channel → channel
      _migrate_dashboard_owners()      # raw SQL: SELECT id, user_id FROM dashboard
      → _flush()
  
  async step6_folder_hierarchy() -> int
      全量查 KnowledgeFile
      _resolve_parent(file) → (parent_type, parent_id)
      file_type=0 → (folder:{id}, parent, {parent})
      file_type=1 → (knowledge_file:{id}, parent, {parent})
      → _flush()
  
  # === 验证 ===
  async verify_all() -> VerifyReport
      采样用户（非admin）+ 采样资源
      for (user, resource): old_check vs new_check
      生成 VerifyReport
  
  # === 工具方法 ===
  _collect(ops: list[TupleOperation])          # 累积到 _buffer
  async _flush() -> int                         # 去重 → 分批 100 → FGAClient.write_tuples()
  _dedup_tuples(tuples) -> list                 # dict key=(user, object) → 保留最高 relation
  _resolve_parent(file) -> (str, str)           # file_level_path → (parent_type, parent_id)
  _load_checkpoint() -> int                     # 读 JSON 文件
  _save_checkpoint(step, stats)                 # 写 JSON 文件
```

### 7.2 _resolve_parent 逻辑

```python
def _resolve_parent(self, file: KnowledgeFile) -> tuple[str, str]:
    """从 file_level_path 推导 parent (type, id)"""
    path = file.file_level_path or ''
    segments = [s for s in path.split('/') if s]
    if not segments:
        # 根级 → parent 是 knowledge_space
        return ('knowledge_space', str(file.knowledge_id))
    # 最后一个 segment 就是直接 parent folder 的 id
    return ('folder', segments[-1])
```

### 7.3 _dedup_tuples 逻辑

```python
def _dedup_tuples(self, tuples: list[TupleOperation]) -> list[TupleOperation]:
    """同一 (user, object) 只保留最高优先级的 relation"""
    best: dict[tuple[str, str], TupleOperation] = {}
    for t in tuples:
        key = (t.user, t.object)
        if key not in best or RELATION_PRIORITY.get(t.relation, 0) > RELATION_PRIORITY.get(best[key].relation, 0):
            best[key] = t
    return list(best.values())
```

### 7.4 启动集成

```python
# init_data.py 末尾
async def _migrate_rbac_to_rebac_if_needed():
    """One-time RBAC→ReBAC migration (F006). Idempotent."""
    from bisheng.core.openfga.manager import get_fga_client
    fga = get_fga_client()
    if fga is None:
        return  # OpenFGA 未启用，跳过
    
    redis = RedisManager.get_client()
    if await redis.get('migration:f006:completed'):
        return  # 已完成，跳过
    
    # SETNX 锁防止多进程并发（TTL=3600s，覆盖大规模迁移场景）
    lock_key = 'migration:f006:lock'
    if not await redis.set(lock_key, '1', nx=True, ex=3600):
        return  # 另一进程正在执行
    
    try:
        migrator = RBACToReBACMigrator(dry_run=False)
        stats = await migrator.run()
        await redis.set('migration:f006:completed', json.dumps({
            'timestamp': datetime.now().isoformat(),
            'stats': stats.to_dict(),
        }))
    finally:
        await redis.delete(lock_key)
```

---

## 8. 前端设计

本 Feature 无前端变更。迁移是纯后端数据操作。

---

## 9. 文件清单

### 新建文件

| 文件路径 | 说明 |
|---------|------|
| `permission/migration/__init__.py` | 包初始化 |
| `permission/migration/migrate_rbac_to_rebac.py` | RBACToReBACMigrator + CLI 入口 |

### 修改文件

| 文件路径 | 变更说明 |
|---------|---------|
| `common/init_data.py` | 末尾添加 `_migrate_rbac_to_rebac_if_needed()` 调用 |

---

## 10. 非功能要求

| 维度 | 要求 |
|------|------|
| 幂等性 | 任意步骤可安全重复执行，不产生重复数据 |
| 性能 | 10 万条元组在 10 分钟内完成（每批 100 条 × FGAClient 写入延迟） |
| 可观测性 | 每步输出进度日志（当前步骤、已处理/总数、耗时）；dry-run 输出完整统计 |
| 容错 | OpenFGA 中断时不丢失进度（checkpoint）；单条失败不阻塞后续（FailedTuple） |
| 兼容性 | Dashboard 表不存在时静默跳过；无 OpenFGA 配置时整体跳过 |
| 安全 | 迁移脚本只读源数据表，只写 OpenFGA 和 checkpoint 文件 |

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- ReBAC 核心: [features/v2.5.0/004-rebac-core/spec.md](../004-rebac-core/spec.md)

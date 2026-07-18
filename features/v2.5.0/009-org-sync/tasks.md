# Tasks: 三方组织同步

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-13 审查通过（2 个 low 已修复） |
| tasks.md | ✅ 已拆解 | 2026-04-13 审查通过（Round 2 LGTM） |
| 实现 | ✅ 已完成 | 17 / 17 完成（2026-04-13） |

---

## 任务列表

### Phase 1: Foundation

#### T-01: OrgSyncConfig + OrgSyncLog ORM 模型与 DAO

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/models/__init__.py`
- 新建: `src/backend/bisheng/org_sync/domain/models/org_sync.py`

**内容**:
- OrgSyncConfig ORM（spec §5 定义），含 tenant_id、所有字段、UniqueConstraint
- OrgSyncLog ORM（spec §5 定义），含 tenant_id、统计字段、error_details JSON
- OrgSyncConfigDao：acreate / aget_by_id / aget_list / aupdate / aset_sync_status / aget_active_cron_configs
- OrgSyncLogDao：acreate / aupdate / aget_by_config（分页）
- 加密/解密辅助函数：encrypt_auth_config / decrypt_auth_config（Fernet，AD-02）

**覆盖 AC**: AC-01（ORM 结构）, AC-02（唯一约束）

**验证**: 单元测试——SQLite in-memory 验证 CRUD + 唯一约束 + 加解密

---

#### T-02: 数据库迁移脚本

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f009_org_sync.py`

**内容**:
- CREATE TABLE org_sync_config（所有列 + 索引 + UK）
- CREATE TABLE org_sync_log（所有列 + 索引）
- ALTER TABLE user ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'local'
- ALTER TABLE user ADD COLUMN external_id VARCHAR(128) NULL
- CREATE UNIQUE INDEX uk_user_source_external_id ON user(source, external_id)

**依赖**: T-01（模型定义确定后写迁移）

**验证**: 在 MySQL 上执行 upgrade/downgrade 无报错

---

#### T-03: 错误码模块 220

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/common/errcode/org_sync.py`

**内容**:
- 10 个错误码类（22000~22009），继承 BaseErrorCode
- 类名遵循 `OrgSync{Error}Error` 命名

**覆盖 AC**: AC-02, AC-08, AC-10, AC-12, AC-14, AC-15, AC-33

**验证**: import 无报错，Code/Msg 属性正确

---

#### T-04: User 模型扩展 + UserDao 新方法

- [x] 完成

**文件**:
- 修改: `src/backend/bisheng/user/domain/models/user.py`

**内容**:
- User 类新增 source 字段（default='local'）+ external_id 字段（nullable）
- 新增 __table_args__ 中的 UniqueConstraint('source', 'external_id')
- UserDao 新增 aget_by_source_external_id(source, external_id)
- UserDao 新增 aget_by_source(source, tenant_id)（查某来源全部用户）

**覆盖 AC**: AC-22（User 匹配依赖 source+external_id）

**验证**: 单元测试——新字段默认值正确，DAO 方法可查询

---

#### T-05: Provider 抽象基类 + 远程 DTO

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/providers/__init__.py`
- 新建: `src/backend/bisheng/org_sync/domain/providers/base.py`
- 新建: `src/backend/bisheng/org_sync/domain/schemas/__init__.py`
- 新建: `src/backend/bisheng/org_sync/domain/schemas/remote_dto.py`

**内容**:
- OrgSyncProvider ABC：authenticate / fetch_departments / fetch_members / test_connection
- get_provider(provider, auth_config) 工厂方法
- RemoteDepartmentDTO：external_id, name, parent_external_id, sort_order
- RemoteMemberDTO：external_id, name, email, phone, primary_dept_external_id, secondary_dept_external_ids, status

**覆盖 AC**: AC-12（Provider 未实现时 raise OrgSyncProviderError）

**验证**: import 无报错，工厂方法对未知 provider 抛出正确错误

---

### Phase 2: Providers

#### T-06: FeishuProvider 完整实现

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/providers/feishu.py`

**内容**:
- authenticate()：POST /auth/v3/tenant_access_token/internal → 获取 tenant_access_token
- fetch_departments()：GET /contact/v3/departments BFS 遍历 + page_token 分页，返回 RemoteDepartmentDTO 列表
- fetch_members()：GET /contact/v3/users?department_id=X 逐部门拉取 + page_token 分页
- test_connection()：authenticate + GET /contact/v3/departments/0 获取根部门元数据
- httpx.AsyncClient，Semaphore(5) 并发控制，429 指数退避重试（1s/2s/4s）
- token 缓存（实例属性，2h 有效期）

**覆盖 AC**: AC-09, AC-10, AC-11

**验证**: mock httpx 响应的单元测试——认证成功/失败、部门分页、人员拉取、429 重试

---

#### T-07: GenericAPIProvider 完整实现

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/providers/generic_api.py`

**内容**:
- authenticate()：根据 auth_type 验证连接（api_key → 带 header/query 参数请求测试端点；password → 基本认证）
- fetch_departments()：GET departments_url，通过 field_mapping 转换为 RemoteDepartmentDTO
- fetch_members()：GET members_url，通过 field_mapping 转换为 RemoteMemberDTO
- test_connection()：authenticate + 基本 GET 验证
- 字段映射逻辑：从 auth_config.field_mapping 读取，有默认映射

**覆盖 AC**: AC-09, AC-11

**验证**: mock httpx 响应的单元测试——标准格式 + 自定义映射 + 格式错误处理

---

#### T-08: WeComProvider + DingTalkProvider stub

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/providers/wecom.py`
- 新建: `src/backend/bisheng/org_sync/domain/providers/dingtalk.py`

**内容**:
- 继承 OrgSyncProvider，4 个方法均 raise OrgSyncProviderError(msg="WeChat Work provider not implemented")
- 类文档注释说明 API 契约（留给后续实现者参考）

**覆盖 AC**: AC-12

**验证**: 调用任何方法均抛出 OrgSyncProviderError

---

### Phase 3: Sync Engine

#### T-09: Reconciler — 部门差异引擎

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/services/__init__.py`
- 新建: `src/backend/bisheng/org_sync/domain/services/reconciler.py`

**内容**:
- reconcile_departments(remote_depts, local_depts, source) → list[DeptOperation]
- DeptOperation 数据类：CreateDept / UpdateDept / MoveDept / ArchiveDept
- 逻辑：构建 remote_map + local_map → 创建/更新/移动/归档判定 → 拓扑排序（创建父先子后，归档子先父后）
- 本地冲突处理：source='local' 的部门匹配远程 → 强制覆盖 + 改 source（AC-18）
- 循环引用检测：拓扑排序发现环 → 记录错误跳过

**覆盖 AC**: AC-16, AC-17, AC-18, AC-19, AC-20, AC-21

**验证**: 纯逻辑单元测试（无 IO），覆盖全部 6 种部门场景 + 循环引用 + 空输入

---

#### T-10: Reconciler — 人员差异引擎

- [x] 完成

**文件**:
- 修改: `src/backend/bisheng/org_sync/domain/services/reconciler.py`

**内容**:
- reconcile_members(remote_members, local_users, local_user_depts, ext_to_local_dept, source) → list[MemberOperation]
- MemberOperation 数据类：CreateMember / UpdateMember / TransferMember / DisableMember / ReactivateMember
- 逻辑：构建 remote_map + local_map → 创建/更新/转岗/禁用/重新激活判定
- 本地冲突处理：source='local' 的用户匹配远程 → 强制覆盖 + 改 source

**覆盖 AC**: AC-22, AC-24, AC-25, AC-26, AC-27, AC-28

**验证**: 纯逻辑单元测试（无 IO），覆盖全部 6 种人员场景 + 本地冲突 + 空输入

---

#### T-11: OrgSyncService — 同步编排器

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/services/org_sync_service.py`

**内容**:
- execute_sync(config_id, trigger_type, trigger_user)：主编排流程（spec §7 的 16 步）
- _apply_dept_ops(ops, config, stats)：执行部门操作（直接 DAO + DepartmentChangeHandler，AD-11）
- _apply_member_ops(ops, config, stats, dept_map)：执行人员操作（User 创建/更新/禁用 + UserDepartment + OpenFGA）
- 互斥锁获取/释放：DB sync_status 原子 UPDATE + Redis 分布式锁（AD-04）
- 部分失败处理：逐条 try/except，累计 error_details（AD-10）
- 新用户密码：secrets.token_hex(32) 生成 64 位随机哈希（AD-07）

**覆盖 AC**: AC-13, AC-14, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-30

**依赖**: T-01, T-04, T-05, T-09, T-10

**验证**: mock Provider + mock DAO 的集成测试——完整同步流程 → 验证 DB 状态 + ChangeHandler 调用

---

### Phase 4: Infrastructure + API

#### T-12: Celery 任务 + Beat 定时调度

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/worker/org_sync/__init__.py`
- 新建: `src/backend/bisheng/worker/org_sync/tasks.py`
- 修改: `src/backend/bisheng/core/config/settings.py`

**内容**:
- execute_org_sync(config_id, trigger_type, trigger_user) Celery task（time_limit=1800, soft_time_limit=1500）
- check_org_sync_schedules() Beat task：每 60s 检查活跃 cron 配置，匹配时间则 dispatch execute_org_sync
- CeleryConf.task_routes 增加 `"bisheng.worker.org_sync.*": {"queue": "knowledge_celery"}`
- beat_schedule 增加 check_org_sync_schedules（schedule=60.0）
- 使用 croniter 库解析 cron_expression 判断是否到期
- **tenant_id 传递**：发送任务时 tenant_id 通过 Celery headers 注入（`inject_tenant_header` signal），Worker 端 `before_task` signal 调用 `set_current_tenant_id()` 恢复到 ContextVar（INV-8）

**覆盖 AC**: AC-31, AC-32

**依赖**: T-11

**验证**: 单元测试——mock OrgSyncService，验证 task dispatch + cron 匹配逻辑

---

#### T-13: 请求/响应 DTO

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/domain/schemas/org_sync_schema.py`

**内容**:
- OrgSyncConfigCreate：provider, config_name, auth_type, auth_config(dict), sync_scope, schedule_type, cron_expression
- OrgSyncConfigUpdate：auth_type, auth_config, sync_scope, schedule_type, cron_expression, status（全部 Optional）
- OrgSyncConfigRead：完整字段，auth_config 脱敏后的 dict
- OrgSyncLogRead：完整字段
- RemoteTreeNode：external_id, name, children（递归）
- mask_sensitive_fields(auth_config: dict) → dict 脱敏函数

**覆盖 AC**: AC-34（脱敏逻辑）

**验证**: 单元测试——序列化/反序列化 + 脱敏函数验证

---

#### T-14: API 端点 — 配置 CRUD + 路由注册

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/__init__.py`
- 新建: `src/backend/bisheng/org_sync/api/__init__.py`
- 新建: `src/backend/bisheng/org_sync/api/router.py`
- 新建: `src/backend/bisheng/org_sync/api/endpoints/__init__.py`
- 新建: `src/backend/bisheng/org_sync/api/endpoints/sync_config.py`
- 修改: `src/backend/bisheng/api/router.py`

**内容**:
- 5 个配置 CRUD 端点（spec §6.1~6.5）：
  1. POST /org-sync/configs — 创建（加密 auth_config）
  2. GET /org-sync/configs — 列表
  3. GET /org-sync/configs/{id} — 详情
  4. PUT /org-sync/configs/{id} — 更新（合并 auth_config）
  5. DELETE /org-sync/configs/{id} — 软删除
- 模块 __init__.py 包文件（org_sync/ + api/ + endpoints/）
- org_sync/api/router.py 路由聚合
- 权限检查：所有端点使用 `LoginUser.access_check` 要求管理员
- 响应包装：UnifiedResponseModel，resp_200 / resp_500
- 路由注册到全局 `api/router.py`

**覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-33, AC-34

**依赖**: T-01, T-03, T-13

**验证**: API 集成测试（TestClient）——配置 CRUD happy path + error path

---

#### T-15: API 端点 — 执行/测试/历史/远程树

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/org_sync/api/endpoints/sync_exec.py`

**内容**:
- 4 个执行端点（spec §6.6~6.9）：
  6. POST /org-sync/configs/{id}/test — 测试连接
  7. POST /org-sync/configs/{id}/execute — 手动触发（dispatch Celery task）
  8. GET /org-sync/configs/{id}/logs — 同步历史（PageData）
  9. GET /org-sync/configs/{id}/remote-tree — 远程树预览
- 权限检查：同 T-14
- execute 端点：检查 sync_status + dispatch Celery task + 返回 log_id
- 路由注册到 org_sync/api/router.py（T-14 已创建）

**覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-29

**依赖**: T-01, T-03, T-05, T-11, T-12, T-14

**验证**: API 集成测试（TestClient）——测试连接 + 手动触发 + 历史查询 + 远程树

---

### Phase 5: Testing

#### T-16: Reconciler 单元测试

- [x] 完成

**文件**:
- 新建: `src/backend/test/test_org_sync_reconciler.py`

**内容**:
- test_dept_create：远程有新部门 → CreateDept
- test_dept_rename_third_party：第三方来源部门改名 → UpdateDept
- test_dept_rename_local：本地来源部门匹配远程 → UpdateDept + source 变更
- test_dept_move：部门层级变更 → MoveDept
- test_dept_archive：远程消失 → ArchiveDept
- test_dept_archive_cascade：归档含本地子部门 → 子部门也归档
- test_dept_topological_order：创建操作父先于子
- test_dept_cycle_detection：循环引用 → 跳过
- test_member_create：新员工 → CreateMember
- test_member_update：信息变更 → UpdateMember
- test_member_transfer：主部门变更 → TransferMember
- test_member_secondary_dept_change：附属部门增减
- test_member_disable：离职 → DisableMember
- test_member_reactivate：重新出现 → ReactivateMember
- test_member_local_conflict：本地用户匹配远程 → 强制覆盖

**覆盖 AC**: AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-24, AC-25, AC-26, AC-27, AC-28

**依赖**: T-09, T-10

---

#### T-17: API 集成测试 + E2E 测试

- [x] 完成

**文件**:
- 新建: `src/backend/test/test_org_sync_api.py`
- 新建: `src/backend/test/e2e/test_e2e_org_sync.py`

**内容**:
- API 集成测试：
  - test_create_config / test_create_duplicate / test_list_configs / test_get_config
  - test_update_config_merge_auth / test_delete_config / test_cross_tenant_rejected
  - test_test_connection_success / test_test_connection_auth_fail
  - test_execute_sync / test_execute_already_running / test_execute_disabled
  - test_get_logs_paginated / test_get_remote_tree
  - test_permission_denied_non_admin
- E2E 测试（mock Provider，真实 DB）：
  - test_full_sync_flow：配置 → 触发 → 验证 Department/User/UserDepartment/OrgSyncLog 状态
  - test_incremental_sync：首次同步后修改远程数据 → 二次同步 → 验证增量变更
  - test_member_disable_on_departure：员工离职 → 验证禁用 + 清理
  - test_multi_tenant_isolation：两个租户各自同步互不影响

**覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34

**依赖**: T-14, T-15

---

## 任务依赖图

```
T-01 (ORM)  ──┬──> T-02 (迁移)
              ├──> T-05 (Provider ABC) ──> T-06 (飞书)
              │                        ──> T-07 (通用API)
              │                        ──> T-08 (企微/钉钉 stub)
T-03 (错误码) ─┤
T-04 (User扩展)┤
              ├──> T-09 (部门Reconciler) ──┐
              ├──> T-10 (人员Reconciler) ──┤
              │                            v
              └──> T-11 (OrgSyncService) <─┘
                       │
                       ├──> T-12 (Celery)
                       │
              T-13 (DTO)┤
                       v
                   T-14 (配置CRUD API)
                       │
                       v
                   T-15 (执行API) ───────> T-17 (API+E2E测试)
                                              ^
                   T-16 (Reconciler测试) ──────┘
```

## 并行策略

- **Wave 1** (可并行): T-01 + T-03 + T-04 + T-05
- **Wave 2** (T-01 完成后): T-02
- **Wave 3** (T-05 完成后，可并行): T-06 + T-07 + T-08
- **Wave 4** (T-01/T-04/T-09/T-10 完成后): T-11
- **Wave 5** (T-11 完成后，可并行): T-12 + T-13
- **Wave 6** (T-13 完成后): T-14
- **Wave 7** (T-14 完成后): T-15
- **Wave 8** (T-15 完成后，可并行): T-16 + T-17

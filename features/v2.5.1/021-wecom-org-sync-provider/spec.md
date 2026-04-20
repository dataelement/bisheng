# Feature: 企业微信组织同步 Provider

**关联 PRD**: [2.5 多租户需求文档.md §9.2 企业微信 Provider 对接详述](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md#92-企业微信-provider-对接详述本期核心)
**关联基线**: [v2.5.0/F009-org-sync spec.md](../../v2.5.0/009-org-sync/spec.md)
**优先级**: P0
**所属版本**: v2.5.1（编号延续上一版 F020；模块职责属于 v2.5.0 org-sync 体系的 Provider 扩展）

---

## 范围界定

- **本 Feature 仅实现**：`WeComProvider` 类（替换 `src/backend/bisheng/org_sync/domain/providers/wecom.py` 中现有 stub）、管理台表单在 Provider 下拉选中"企业微信"时的配置字段、测试连接/远程树预览在企微下的行为、与之匹配的 i18n 文案与 E2E 测试。
- **依赖（不在本 Feature 实现）**：`OrgSyncConfig` / `OrgSyncLog` ORM、Reconciler 引擎、`OrgSyncProvider` ABC、9 个 REST 端点、Celery Beat 调度任务、错误码 220xx —— 全部由 **v2.5.0/F009** 提供。
- **本期明确不做**：企微 `change_contact` 实时事件回调；企微 OAuth SSO 登录；企微外部联系人同步；同 tenant 下多 agent_id 同步（均延后到 v2.5.2+）。

---

## 1. 概述与用户故事

作为 **系统管理员（集团总部 IT/运营）**，
我希望 **在 bisheng 管理台配置企业微信 corpid/corpsecret/agent_id，启用定时拉取部门与成员信息，让企微通讯录中启用状态的员工自动落到 bisheng 并归属到正确的部门**，
以便 **集团 10 万人通讯录无需人工维护，且人员离职/转岗能在下一次同步周期（≤ 6h）内自动反映到 bisheng 的权限与 Tenant 归属上**。

---

## 2. 验收标准

> 本 Feature 的 AC 编号**延续 F009 AC-01~AC-34**，从 **AC-35** 起自新号。
> 未列出的 AC（同步执行入口、定时调度、权限审计等）由 F009 基线覆盖，不重复定义。

### 配置字段（企微专属）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-35 | 管理员 | 在"新增同步配置"表单 Provider 下拉选择"企业微信" | 表单切换显示 3 个必填字段（corpid、corpsecret、agent_id）+ 1 个可选字段（allow_dept_ids，JSON 数组） |
| AC-36 | 管理员 | 提交配置时缺失 corpid / corpsecret / agent_id 任一字段 | HTTP 200 返回 `22006 OrgSyncInvalidConfigError`，`data=null`，提示「企业微信配置缺少必填字段：{field_name}」 |
| AC-37 | 管理员 | 提交配置时 `allow_dept_ids` 非数组或含非整数 | HTTP 200 返回 `22006 OrgSyncInvalidConfigError`，提示「allow_dept_ids 必须是整数数组」 |
| AC-38 | 管理员 | 查看已创建的企微同步配置（GET /org-sync/configs/{id}） | 响应中 `corpsecret` 字段值为 `****`，`corpid` / `agent_id` / `allow_dept_ids` 明文返回 |

### 测试连接（企微专属）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-39 | 管理员 | 点击"测试连接"，企微返回合法 access_token + 部门 1 存在 | 返回 `{connected: true, org_name: "<企业简称>", total_depts: N, total_members: M}`，响应中不含任何 token 字段 |
| AC-40 | 管理员 | 测试连接时 corpid/corpsecret 错误（企微返回 errcode=40001 或 40013） | HTTP 200 返回 `22002 OrgSyncAuthFailedError`，提示包含"access_token 获取失败"但**不泄露** corpsecret |
| AC-41 | 管理员 | 测试连接时 agent_id 对应应用在"通讯录可见范围"内无任何部门权限（企微返回 errcode=60011） | HTTP 200 返回 `22002 OrgSyncAuthFailedError`，提示"应用无权限访问通讯录，请检查企业微信后台可见范围" |

### 部门同步

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-42 | 系统 | Provider `fetch_departments(root_dept_ids=None)` 默认拉取 | 调用 `GET /cgi-bin/department/list?id=1` 一次拉到子树全部部门；返回 `RemoteDepartmentDTO[]`，`parent_external_id` 在 root=1 处置 None |
| AC-43 | 系统 | Provider 读取配置 `allow_dept_ids=[1, 2]` | 对每个 root 分别调一次 `department/list?id=X`，合并去重（按 external_id），root 节点自身 `parent_external_id=None` |
| AC-44 | 系统 | 响应中 `id`、`parentid` 为整数 | DTO 中 `external_id`、`parent_external_id` 转为字符串写入；`sort_order` 取 `order` 字段（缺失置 0） |

### 成员同步

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-45 | 系统 | Provider `fetch_members(department_ids=None)` 默认拉取 | 对 `allow_dept_ids`（默认 `[1]`）每个 root 调用一次 `GET /cgi-bin/user/list?department_id=X&fetch_child=1` |
| AC-46 | 系统 | 企微成员响应包含 `main_department` 字段 | DTO `primary_dept_external_id` = `str(main_department)`，`secondary_dept_external_ids` = 除 main 外的 department 列表（转字符串） |
| AC-47 | 系统 | 企微成员响应未返回 `main_department`（老版本 API） | DTO `primary_dept_external_id` = `str(department[0])`，其余进 secondary |
| AC-48 | 系统 | 企微 `status=1` / `status=2 / 4 / 5` | DTO `status` 分别为 `active` / `disabled`（4=未激活、5=退出均归 disabled） |
| AC-49 | 系统 | 成员 `userid` 在多个顶层 root 下都出现（兼职） | Provider 内部去重，同一 userid 只产生一条 DTO，`secondary_dept_external_ids` 合并所有部门 |

### Token 与限流

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-50 | 系统 | 首次调用业务 API 前 | 调 `GET /cgi-bin/gettoken`，成功则写 Redis `org_sync:wecom:token:{config_id}`，TTL = `expires_in - 300`（默认 6900s） |
| AC-51 | 系统 | Token 仍在有效期内再次调用 | 直接读 Redis 缓存，不触发 gettoken |
| AC-52 | 系统 | 两并发任务同时需要刷新 token | Redis 分布式锁 `org_sync:wecom:token_lock:{config_id}`（TTL 30s）确保只有一个请求真实调用 gettoken，另一个等待后读缓存 |
| AC-53 | 系统 | 业务 API 响应 `errcode=42001` 或 `40014` | Provider 主动删除 Redis token key，重新 gettoken，再重试原调用一次；第二次仍失败则抛 `OrgSyncFetchError` |
| AC-54 | 系统 | 业务 API 响应 `errcode=45009 / 45033 / 45011`（限流） | 指数退避 `[1s, 2s, 4s, 8s]`，最多重试 4 次；仍失败则 `OrgSyncFetchError`，上层 Reconciler 将本次 sync 标记 `partial` |

### 字段回写 & 安全

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-55 | 系统 | 同步创建的新用户 | `user.source='wecom'`，`user.external_id=<企微 userid>`，触发 F009 `DepartmentChangeHandler.on_members_added` |
| AC-56 | 系统 | 本地存在 `source='local'` 且 email 匹配企微成员的用户 | 按 F009 第 7 条规则覆盖合并：`source` 改为 `wecom`、写入 `external_id`、不创建重复账号 |
| AC-57 | 系统 | `org_sync_log.error_details` 记录失败成员 | 手机号/邮箱按 `mask_sensitive_fields()` 脱敏；userid 保留首 2 字与末 2 字，中间以 `*` 代替（例：`za****ng`） |
| AC-58 | 系统 | 任何接口响应 / 日志 / 审计 | **永不**包含 `access_token` 原文或 `corpsecret` 原文 |

---

## 3. 边界情况

- **企微后台关闭了通讯录同步助手**：`gettoken` 可能返回 42009 → 归入 `OrgSyncAuthFailedError`，提示「企业微信后台未授权该应用访问通讯录」
- **企微临时 API 故障（5xx / 超时）**：httpx 默认超时 30s，按 `asyncio.TimeoutError` 进入限流重试链路
- **10 万人下 `user/list?fetch_child=1` 响应超大**：企微单次返回上限约 1 万人；超过则企微返回错误 `errcode=301036` → 文档记录：建议客户配置 `allow_dept_ids` 分批拉取，具体拆分规则由客户运营决定
- **configuration 同时存在 `active` 状态的企微配置 + 飞书配置**：两者相互独立；同一 email 被两个源匹配时按 F009 规则处理（先到先得 + 跨源冲突跳过）
- **不支持**：`change_contact` 事件回调（v2.5.2）、企微 OAuth 扫码登录（Gateway 对接）、外部联系人、多 agent_id 合并

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | Provider 内部 HTTP 客户端 | A: httpx.AsyncClient 按调用独立创建 / B: Provider 实例持有一个 client | **A** | 与 F009 Feishu 实现一致，便于 Reconciler 单次调用的生命周期管理；复用 Feishu 相同的 `_request` 辅助方法签名 |
| AD-02 | 限流实现位置 | A: Provider 内 `asyncio.Semaphore` / B: Celery 队列限速 | **A** | Feishu 已采用 Semaphore(5)；统一风格；Celery 队列限速会影响其他 Provider |
| AD-03 | Token 缓存后端 | A: Redis / B: Provider 实例内存 | **A** | 多 Worker 并发下内存缓存会导致 token 频繁刷新并接近 QPS 限制；Redis 跨 Worker 共享 |
| AD-04 | Token 失效后的重试粒度 | A: 单次调用重试一次 / B: 整个 fetch 任务重试 | **A** | B 会放大已写入数据的幂等风险；A 足够处理 42001/40014 且无副作用 |
| AD-05 | `allow_dept_ids` 默认值 | A: `[1]`（企微根部门） / B: None → 全量 | **A** | 企微 `department/list` 不接受空 id，必须给一个根；`1` 是企微固定的默认根 ID |
| AD-06 | 管理台 Provider 表单 | A: 硬编码 WeCom 字段集 / B: Schema 驱动 | **A** | F009 前端当前未实现；先按硬编码走最快路径；schema 驱动动态表单留 v2.5.2 再做 |
| AD-07 | 脱敏规则（userid） | A: 全脱敏 / B: 保首末 2 字 | **B** | 审计/排查需要部分可识别；全脱敏会失去定位能力；符合 F009 `mask_sensitive_fields` 现有风格 |

---

## 5. 数据库 & Domain 模型

**本 Feature 不新建任何表、不改动任何表字段。** 全部复用 F009：

- `org_sync_config`（`provider='wecom'` 时 `auth_config` 字段 JSON 包含 `corpid / corpsecret / agent_id / allow_dept_ids`）
- `org_sync_log`（复用）
- `user.source` / `user.external_id`（F009 alembic 已加）

### WeCom `auth_config` JSON Schema（逻辑上的契约，不建表）

```json
{
  "corpid": "wwa04427c3f62b5769",         // 必填，企业 ID
  "corpsecret": "qVldC5Kp5houi1fG8...",   // 必填，Fernet 加密存储，API 响应脱敏
  "agent_id": "1000017",                   // 必填，应用 AgentId（字符串）
  "allow_dept_ids": [1]                    // 可选，整数数组，默认 [1]
}
```

### 脱敏规则扩展

修改 `src/backend/bisheng/org_sync/domain/schemas/org_sync_schema.py` 的 `mask_sensitive_fields()`：

- 当 `provider='wecom'` 时，需要脱敏字段：`corpsecret`
- 保留明文字段：`corpid`、`agent_id`、`allow_dept_ids`

---

## 6. API 契约

**本 Feature 不新增任何 REST 端点。** 完全复用 F009 的 9 个端点：

| Method | Path | WeCom 下行为差异 |
|--------|------|-----------------|
| POST | `/org-sync/configs` | `auth_config` 校验 corpid/corpsecret/agent_id 非空；allow_dept_ids 可选 |
| GET | `/org-sync/configs` / `/org-sync/configs/{id}` | corpsecret 脱敏为 `****` |
| PUT | `/org-sync/configs/{id}` | 部分更新 auth_config 时不覆盖未提交字段；corpsecret 传 `****` 表示"保留原值" |
| POST | `/org-sync/configs/{id}/test` | 走 WeComProvider.test_connection()（见 §7） |
| POST | `/org-sync/configs/{id}/execute` | 走 WeComProvider → Reconciler |
| GET | `/org-sync/configs/{id}/logs` | 无差异 |
| GET | `/org-sync/configs/{id}/remote-tree` | 走 WeComProvider.fetch_departments() 后本地重建树 |
| DELETE | `/org-sync/configs/{id}` | 无差异 |

### 错误码（复用 F009 220 段，不新增）

| Code | Class | WeCom 触发场景 | 关联 AC |
|------|-------|---------------|---------|
| 22002 | OrgSyncAuthFailedError | gettoken 401/40013/60011/42009 | AC-40, AC-41 |
| 22004 | OrgSyncProviderError | 未知 errcode | AC-53 尾分支 |
| 22006 | OrgSyncInvalidConfigError | corpid/corpsecret/agent_id 缺失或 allow_dept_ids 非法 | AC-36, AC-37 |
| 22007 | OrgSyncFetchError | 限流重试耗尽 / 网络错误 | AC-54 |

---

## 7. Service 层逻辑

### 7.1 WeComProvider 类结构

> 文件：`src/backend/bisheng/org_sync/domain/providers/wecom.py`（替换现有 stub）

```
WeComProvider(OrgSyncProvider):
  __init__(auth_config): 校验 corpid/corpsecret/agent_id 非空；存字段；初始化 Semaphore(5)

  # 私有辅助
  async _get_token_from_redis(config_id) -> Optional[str]
  async _acquire_token_lock(config_id) -> bool
  async _release_token_lock(config_id)
  async _fetch_new_token(client) -> (token, expires_in)
  async _ensure_token(config_id, client) -> str
     # 1. 读 Redis；命中则返回
     # 2. 获取分布式锁；获取失败则 sleep 200ms 再读 Redis
     # 3. 持锁 → gettoken → 写 Redis TTL=expires_in-300 → 释放锁 → 返回

  async _invalidate_token(config_id)
  async _request(client, method, url, config_id, **kwargs) -> dict
     # asyncio.Semaphore 限并发
     # 若响应 errcode=42001/40014 → invalidate → ensure_token → 重试一次
     # 若响应 errcode=45009/45033/45011 → 指数退避 [1,2,4,8] s
     # 其余非零 errcode → 根据映射抛 OrgSyncAuthFailedError / OrgSyncFetchError

  # 公共接口
  async authenticate() -> bool
  async fetch_departments(root_dept_ids: Optional[list[str]]) -> list[RemoteDepartmentDTO]
  async fetch_members(department_ids: Optional[list[str]]) -> list[RemoteMemberDTO]
  async test_connection() -> dict
     # 1. gettoken 成功
     # 2. 取 allow_dept_ids[0] （默认 1）调 department/list，获取 total_depts
     # 3. 调 user/simplelist 获取 total_members
     # 4. 组装响应（不含 token）
```

### 7.2 权限检查

仅全局超管 + 租户管理员可 CRUD `OrgSyncConfig`（F009 AC-33 已覆盖，此处不额外设计）。

### 7.3 与 F009 Reconciler 的集成点

无代码改动需要。`org_sync_service.py` 已按 `get_provider(provider, auth_config)` 动态实例化 Provider；替换 stub 后自动走通。

### 7.4 `config_id` 传递

当前 Provider `__init__` 只收 `auth_config`；WeCom 需要 `config_id` 作为 Redis key 后缀。两种方案：

- **选择**（AD-08，新增决策）：在 `auth_config` 字典中由调用方注入 `_config_id` 字段（下划线前缀表示内部字段，入库前剥离）。`OrgSyncService.execute_sync()` 调 `get_provider` 前把 `config_id` 塞进 auth_config；Provider 内部读 `self.auth_config.get('_config_id')`；加密回写 DB 前由 Service 层 pop 掉 `_config_id`。
- 备选方案（修改 ABC 签名）风险大，影响 Feishu / GenericAPI。本方案零侵入。

此决策在 spec.md 中明确；实现需在 tasks.md 中落点。

---

## 8. 前端设计

### 8.1 Platform 前端

> 路径：`src/frontend/platform/src/`
> 当前项目**未实现** F009 前端页面（F009 只完成后端 + E2E 测试）；本 Feature 首次落地"组织同步"入口。

**页面路由**: `/system/org-sync` → `pages/SystemPage/OrgSyncPage/`（建议放在系统管理二级菜单下）

**组件**:

```
OrgSyncPage/
├── index.tsx                      # 列表 + 新建入口
├── ConfigFormModal.tsx            # 新建/编辑表单（Provider 下拉 + 动态字段）
├── components/
│   ├── WeComFieldSet.tsx          # 企微字段组（本 Feature 实现）
│   ├── FeishuFieldSet.tsx         # 飞书字段组（本 Feature 实现，便于验收 F009 已有能力）
│   └── GenericApiFieldSet.tsx     # Generic API 字段组（本 Feature 实现）
├── TestConnectionButton.tsx       # 测试连接按钮（调 POST /org-sync/configs/{id}/test）
├── SyncHistoryTable.tsx           # 同步历史（分页）
└── hooks/
    └── useOrgSyncConfig.ts        # 数据请求 + Zustand 集成
```

**状态管理**: 新建 Zustand store `src/store/orgSyncStore.ts`（列表状态、当前配置、loading）

**API 层**: 新建 `src/controllers/API/orgSync.ts`，封装 F009 的 9 个端点；严格走 `@/controllers/request`

**i18n**:
- 新增 namespace key 前缀 `orgSync.*`
- 至少需要文案：Provider 选项标签（`企业微信` / `飞书` / `通用 REST API`）、字段标签（corpid / corpsecret / agent_id / allow_dept_ids）、表单校验提示、测试连接结果提示、同步状态标签
- 三语齐全：`public/locales/en-US/bs.json` / `zh-Hans/bs.json` / `ja/bs.json`

### 8.2 Client 前端

不涉及。组织同步是管理端能力。

---

## 8.5 自测清单（对应 AC）

> 开发者在完成实现后必须自行运行以下测试；不依赖用户/产品人肉点击。企微 API 用 mock httpx client；E2E 用 Playwright 覆盖前端流程。

| Test | AC | 类型 | 备注 |
|------|----|------|------|
| `test_wecom_form_fields_switch_on_provider_change` | AC-35 | 前端 Vitest | 下拉切换到企业微信，显示 3 必填 + 1 可选字段 |
| `test_wecom_config_missing_field_rejected` | AC-36 | pytest 单元测试 | 缺 corpid/corpsecret/agent_id 返 22006 |
| `test_wecom_config_invalid_allow_dept_ids` | AC-37 | pytest 单元测试 | 非整数数组返 22006 |
| `test_wecom_config_response_masks_corpsecret` | AC-38 | pytest 集成测试 | GET 响应 corpsecret='****' |
| `test_wecom_test_connection_success` | AC-39 | pytest 集成测试 | mock 企微 API，返回 connected/org_name/total 等；不含 token |
| `test_wecom_test_connection_auth_failed` | AC-40 | pytest 集成测试 | mock errcode=40001/40013 返 22002，不泄露 corpsecret |
| `test_wecom_test_connection_no_scope` | AC-41 | pytest 集成测试 | mock errcode=60011 返 22002 + 提示文案 |
| `test_wecom_fetch_departments_default_from_root_1` | AC-42 | pytest 单元测试 | 默认 root=1 拉取 + DTO 转换 |
| `test_wecom_fetch_departments_with_allow_dept_ids` | AC-43 | pytest 单元测试 | 多 root 合并去重 |
| `test_wecom_department_id_type_conversion` | AC-44 | pytest 单元测试 | int → str + sort_order 取 order |
| `test_wecom_fetch_members_default` | AC-45 | pytest 单元测试 | 默认 allow_dept_ids=[1]，fetch_child=1 |
| `test_wecom_member_main_department_handling` | AC-46 | pytest 单元测试 | primary = main_department，secondary = 其他 |
| `test_wecom_member_main_department_fallback` | AC-47 | pytest 单元测试 | 缺失 main_department 时取 department[0] |
| `test_wecom_member_status_mapping` | AC-48 | pytest 单元测试 | status=1 → active；2/4/5 → disabled |
| `test_wecom_duplicate_userid_dedup_across_roots` | AC-49 | pytest 单元测试 | 多 root 下同 userid 只产生一条 DTO |
| `test_wecom_token_cached_in_redis` | AC-50 | pytest 集成测试 | Redis key + TTL = expires_in - 300 |
| `test_wecom_token_cache_hit_skips_gettoken` | AC-51 | pytest 集成测试 | 缓存有效期内不调用 gettoken |
| `test_wecom_token_refresh_concurrency_lock` | AC-52 | pytest 集成测试 | 并发仅一个真实 gettoken；其余等待读缓存 |
| `test_wecom_token_expired_retries_once` | AC-53 | pytest 单元测试 | errcode=42001/40014 重新 gettoken 并重试一次 |
| `test_wecom_rate_limit_exponential_backoff` | AC-54 | pytest 单元测试 | errcode=45009/45033/45011 指数退避 4 次 |
| `test_wecom_new_user_writes_source_and_external_id` | AC-55 | pytest 集成测试 | source=wecom、external_id 写入；触发 F009 handler |
| `test_wecom_local_user_merged_by_email` | AC-56 | pytest 集成测试 | source=local 且 email 匹配时合并不建重复账号 |
| `test_wecom_log_masks_sensitive_fields` | AC-57 | pytest 单元测试 | error_details 手机号/邮箱脱敏；userid 保留首末 2 字 |
| `test_wecom_no_plaintext_token_or_secret_in_logs` | AC-58 | pytest 集成测试 | 所有响应/日志不含 access_token / corpsecret 原文 |
| `test_e2e_org_sync_wecom_full_flow` | AC-35~58 综合 | Playwright E2E | WeCom 配置 → 测试连接 → 手动触发 → 查看 log，前端测试框架搭建后落地 |

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/index.tsx` | 列表页 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/ConfigFormModal.tsx` | 新建/编辑表单 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/components/WeComFieldSet.tsx` | 企微字段组 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/components/FeishuFieldSet.tsx` | 飞书字段组 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/components/GenericApiFieldSet.tsx` | GenericAPI 字段组 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/TestConnectionButton.tsx` | 测试连接 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/SyncHistoryTable.tsx` | 同步历史 |
| `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/hooks/useOrgSyncConfig.ts` | 数据钩子 |
| `src/frontend/platform/src/store/orgSyncStore.ts` | Zustand store |
| `src/frontend/platform/src/controllers/API/orgSync.ts` | API 封装 |
| `src/backend/test/test_wecom_provider.py` | WeComProvider 单测（mock httpx） |
| `src/backend/test/e2e/test_e2e_org_sync_wecom.py` | E2E：WeCom 配置 → 测试连接 → 手动触发 → 查看 log |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/org_sync/domain/providers/wecom.py` | 替换 stub 为完整实现（见 §7.1） |
| `src/backend/bisheng/org_sync/domain/services/org_sync_service.py` | 调 `get_provider` 前把 `_config_id` 注入 auth_config；入库前 pop |
| `src/backend/bisheng/org_sync/domain/schemas/org_sync_schema.py` | `mask_sensitive_fields()` 扩展 WeCom 字段（corpsecret） + 配置 schema 校验 |
| `src/frontend/platform/src/components/bs-comp/menus/index.tsx` 或同等入口 | 添加「组织同步」二级菜单项 |
| `src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/bs.json` | 新增 `orgSync.*` 文案（三语） |

---

## 10. 非功能要求

- **性能**：10 万人全量同步 < 10 min（企微 QPS 60/min 限制）；超过 15 min 触发 `org_sync_log.error_details` 告警标记
- **安全**：
  - `access_token` / `corpsecret` 永不出现在 API 响应、日志、审计条目、前端网络面板
  - 凭证按 F009 Fernet 机制加密入库
  - 所有管理台操作按 `org_sync.config.*` 写 audit_log（由 F009 已实现）
- **兼容性**：
  - 不改动 `OrgSyncProvider` ABC 签名（见 AD-08 内部字段方案）
  - Feishu / GenericAPI Provider 行为不变
  - 不影响单租户模式（多租户关闭时也可配企微，`tenant_id=1` 落 Root Tenant）
- **多租户行为**：`org_sync_config.tenant_id` 由 SQLAlchemy event 自动注入；每个 Tenant 可独立配置自己的企微应用；Child Tenant 管理员可为本 Child 配置（AD-11 由 F019/F020 的 admin_scope 决定可见性，本 Feature 不扩展）

---

## 相关文档

- 版本契约: [features/v2.5.1/release-contract.md](../release-contract.md)（写 spec 前必须先阅读）
- 基线 Feature: [features/v2.5.0/009-org-sync/spec.md](../../v2.5.0/009-org-sync/spec.md)
- PRD: [2.5 多租户需求文档.md §9.2](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md#92-企业微信-provider-对接详述本期核心)
- 企微开放文档: https://developer.work.weixin.qq.com/document/path/90208

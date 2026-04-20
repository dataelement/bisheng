# F020-llm-tenant-isolation AC 对照表

**生成时间**: 2026-04-21
**分支**: `feat/v2.5.1/020-llm-tenant-isolation`（base=`2.5.0-PM`，commit `ee6d24e61`）
**Worktree**: `/Users/lilu/Projects/bisheng-worktrees/020-llm-tenant-isolation`
**本地 pytest 环境**: 不可用（无 `.venv`），所有自动化测试**待 114 环境执行**
**F020 测试套件（新增）**: 5 个文件
  - `test_f020_migration.py` — 3 用例（Alembic 迁移）
  - `test_llm_tenant_isolation_dao.py` — 16 用例（LLMDao 写方法）
  - `test_llm_tenant_isolation_service.py` — 14 用例（LLMService 含 only_shared）
  - `test_llm_tenant_isolation_api.py` — 8 用例（Router 静态依赖检查）

---

## AC → 测试 / 代码路径映射（24 条）

### 2.1 Root 默认共享（决策 2）

| AC | 描述 | 自动化测试 | 代码路径 | 手工 QA |
|----|------|-----------|----------|---------|
| **AC-01** | 超管 POST `/llm` 默认 `share_to_children=true` → 写 FGA `{llm_server}#shared_with → tenant:{child}` 每 Child | `test_llm_tenant_isolation_dao.py::test_root_llm_default_shared_writes_viewer_tuple` | DAO: `llm_server.py::ainsert_server_with_models` L130-174；调 `ResourceShareService.enable_sharing` | 114 §1：超管创建模型 → `bisheng_fga` store 观察 `llm_server:{id}#shared_with` 元组 |
| **AC-02** | 超管 POST 勾选 `share_to_children=false` → 不写 FGA | `test_llm_tenant_isolation_dao.py::test_root_llm_share_off_skips_viewer_tuple` | 同 DAO；false 分支跳过 `ResourceShareService.enable_sharing` | §2 |
| **AC-03** | Child 用户 GET `/llm` → 本 Child + Root 共享合并 | `test_llm_tenant_isolation_service.py::test_child_user_llm_list_merges_root_shared` + `test_aget_shared_server_ids_for_leaf_returns_root_shared` | Service: `get_all_llm` L35-87（bypass + 合并）；DAO: `aget_shared_server_ids_for_leaf` L508-554 | §3：Child 5 用户登录 `/model/manage` 看到本 Child + Root 共享（带 Badge） |
| **AC-04** | 超管 PUT `{share_to_children: false}` → FGA 元组撤销 | `test_toggle_root_llm_share_enables_fga_tuple` / `_off_removes_fga_tuple` | DAO: `aupdate_server_share` L176-205；Service: `update_llm_server` 分发 L279-286 | §4 |

### 2.2 Child Admin 完全自主（决策 3）

| AC | 描述 | 自动化测试 | 代码路径 | 手工 QA |
|----|------|-----------|----------|---------|
| **AC-05** | Child Admin POST → `tenant_id=5`，不写 FGA | `test_child_admin_creates_own_llm_not_shared` + Router `test_post_llm_uses_tenant_admin_dep` | DAO: `ainsert_server_with_models` tenant_id 填充 L127-130；Router: `post /llm` 依赖 `get_tenant_admin_user` | §5：预设 Child Admin（FGA `user:X#admin tenant:5`）登录注册模型 → DB `tenant_id=5` |
| **AC-06** | Child Admin PUT 本 Child 模型 → 200 | `test_put_llm_uses_tenant_admin_dep`（Router dep）+ Service 链路 | Router: `put /llm` 依赖 `get_tenant_admin_user` L29；DAO 允许同 tenant 写 | §6 |
| **AC-07** | Child Admin DELETE 本 Child 模型 → 200 + FGA 清理（幂等） | `test_delete_llm_uses_tenant_admin_dep` + DAO `test_delete_missing_server_raises_19802`（边界） | Router: `delete /llm` 依赖 L25；DAO: `adelete_server_by_id` L420-456 | §7 |
| **AC-08** | Child Admin PUT Root 共享模型 → 403 + 19801 | `test_llm_tenant_isolation_dao.py::test_child_admin_cannot_update_root_shared_llm` + UI `CustomTableRow` disabled 编辑 | DAO: `update_server_with_models` L227-251（bypass 查 + Root 检测）；UI: `index.tsx::CustomTableRow::canEdit` L26 | §8 |
| **AC-09** | Child Admin DELETE Root 共享模型 → 403 + 19801 | `test_child_admin_cannot_delete_root_shared_llm` | DAO: `adelete_server_by_id` L420-440 | §9 |
| **AC-10** | Child Admin 改其它 Child 模型 → 不可见（event 过滤）404/403 | DAO `test_child_admin_cross_child_access_denied`（通过 event filter） | `tenant_filter.py` event 自动 `WHERE tenant_id=leaf` | §10 |
| **AC-11** | Child Admin 调 `POST /llm/workbench` → 403 + 19803 | Router `test_workbench_endpoint_stays_super_admin_only` / `test_knowledge_config_endpoint_stays_super_admin_only` / `test_assistant_config_endpoint_stays_super_admin_only` | Router: 4 系统级端点保持 `get_admin_user`（D9） | §11 |
| **AC-12** | CRUD 写 audit_log，`api_key_hash = sha256(key)[:16]`，不存明文 | `test_llm_tenant_isolation_service.py::test_api_key_hash_is_16_char_sha256_prefix` + `_returns_none_when_no_key_field` + `_accepts_alternative_field_name` | Service: `_llm_api_key_hash` + `_write_llm_audit` L33-86 | §12：触发 CRUD 后 `SELECT * FROM audit_log WHERE action LIKE 'llm.server.%'` |

### 2.3 全局超管 + admin-scope（F019 集成）

| AC | 描述 | 自动化测试 | 代码路径 | 手工 QA |
|----|------|-----------|----------|---------|
| **AC-13** | 超管 scope=5 调 `/llm` → 返本 Child 5 + Root 共享 | `test_super_admin_with_scope_acts_as_child` | Service: `get_all_llm` 读 `get_current_tenant_id()`（F019 scope override） | §13：ModelPage tab 切 Child 5 → 列表变化 |
| **AC-14** | 超管 scope=5 POST `/llm` → `tenant_id=5` | `test_super_admin_with_scope_acts_as_child` | DAO: `ainsert_server_with_models` tenant_id 来自 `get_current_tenant_id`（scope 覆盖） | §14 |
| **AC-15** | 超管无 scope GET `/llm` → Root 全部（含 share=false） | `test_super_admin_without_scope_sees_all_root` + `test_get_all_llm_dedupes_leaf_vs_shared_overlap` | Service: leaf=1 走 `aget_shared_server_ids_for_leaf` short-circuit → [] | §15 |

### 2.4 存量升级零成本（决策 4）

| AC | 描述 | 自动化测试 | 代码路径 | 手工 QA |
|----|------|-----------|----------|---------|
| **AC-16** | v2.4 升级 → `llm_server.tenant_id=1`（F001 迁移） | `test_f020_migration.py::test_upgrade_creates_composite_unique_index` + `_rejects_duplicate_tenant_name_pairs` + `_skips_drop_when_legacy_index_absent` | Migration: `v2_5_1_f020_llm_tenant.py`；F001 历史迁移已回填 | §16：114 导入 v2.4 SQL dump → `alembic upgrade head` → 验证 |
| **AC-17** | 挂载 Child 弹窗预览 Root 共享模型列表 | `test_llm_tenant_isolation_service.py::test_mount_child_preview_shared_llm_list` + `test_mount_child_preview_forbidden_for_non_super_admin` | Router: `GET /llm?only_shared=true`；Service: `_list_shared_root_servers` | §17：`GET /api/v1/llm?only_shared=true` 返共享列表（UI 集成归 F011 后续） |
| **AC-18** | 挂载默认 → 存量 Root 模型对 Child 可见 | DAO 合约测试 `test_llm_server_registered_in_shareable_types`（F017 `on_child_mounted` 已测） | T02b `SUPPORTED_SHAREABLE_TYPES` 加 `llm_server`；F017 `distribute_to_child` 自动处理 | §18 |
| **AC-19** | 挂载勾选 "不自动分发" → Child 初始不可见 | 同上 + F017 `auto_distribute=False` 行为 | F017 `ChildMountService.on_child_mounted(auto_distribute=False)` | §19 |
| **AC-20** | 存量知识库引用 Root 模型 Child 调用正常 | `test_get_model_for_call_root_shared_accessible_for_child` | Service: `get_model_for_call` bypass 查后验证 server_id 在 shared_ids | §20 |
| **AC-21** | Root 模型改为 "仅 Root" 后 Child 知识库报错 | `test_knowledge_model_inaccessible_raises_19802` (逻辑相同，T11a knowledge endpoint 升级错误码) | Service `get_model_for_call` → 19802；knowledge endpoint 升级错误码 | §21 |

### 2.5 跨 Tenant 模型引用

| AC | 描述 | 自动化测试 | 代码路径 | 手工 QA |
|----|------|-----------|----------|---------|
| **AC-22** | Child 5 引用自家模型 → 正常 | `test_get_model_for_call_own_model_returns` | Service `get_model_for_call` 第一次命中 | §22 |
| **AC-23** | 模型被改 `tenant_id=7` 后 Child 5 调用 → 19802 | `test_get_model_for_call_cross_child_raises_19802` + `test_get_model_for_call_unknown_id_raises_19802` | Service bypass 查 server_id 不在 shared_ids → 19802 | §23 |
| **AC-24** | Child Admin 选型跨 Tenant 模型 → 400 + 19802 | Knowledge endpoint 错误码升级（`test_knowledge_model_select_validates_visibility` 列入 T11a 规格但无独立测，覆盖在 T07 get_model_for_call 边界） | `knowledge/api/endpoints/knowledge.py::update_knowledge_model` L860 改错误码 | §24 |

---

## 执行清单（待 114 环境运行）

```bash
cd /opt/bisheng-f020/src/backend  # 114 worktree，具体路径按 deploy.sh 结果

# 1) F020 自动化（预期全绿）
.venv/bin/pytest -v \
  test/test_f020_migration.py \
  test/test_llm_tenant_isolation_dao.py \
  test/test_llm_tenant_isolation_service.py \
  test/test_llm_tenant_isolation_api.py

# 2) F011/F012/F013/F017/F019 回归（确认 F020 未破坏依赖）
.venv/bin/pytest -v \
  test/test_tenant_context_vars.py \
  test/test_user_payload_tenant.py \
  test/test_admin_tenant_scope_api.py \
  test/test_admin_scope_middleware.py \
  test/test_resource_share_service.py \
  test/test_tenant_mount_service.py \
  test/test_openfga_authorization_model.py

# 3) Alembic 迁移演练（v2.4 SQL dump）
.venv/bin/alembic upgrade head
mysql -e "SHOW CREATE TABLE llm_server\G" bisheng | grep uk_llm_server_tenant_name  # 确认索引

# 4) 前端 TS 构建
cd src/frontend/platform && npm run build
```

---

## 手工 QA（114 浏览器验证）

| # | 角色 | 操作 | 预期 |
|---|------|------|------|
| §1 | 超管 | `/model/manage` 顶部无 scope tabs 时，POST 新建模型（API 默认 share_to_children=true）| DB `llm_server.tenant_id=1`；FGA `llm_server:{id}#shared_with → tenant:{child}` 每 Child；audit_log `action=llm.server.create + share_to_children=true` |
| §2 | 超管 | 同上但勾选 "share_to_children: false" | FGA 无 shared_with 元组；audit_log `share_to_children=false` |
| §3 | Child 5 用户 | 登录 → `/model/manage` | 列表含本 Child 5 + Root 共享；Root 行 Badge "Root 共享 · 只读"；编辑按钮 disabled |
| §4 | 超管 | PUT 切换 Root 模型 share 开关 | FGA 元组动态增删；Child 用户再次 GET 反映变化 |
| §5 | Child Admin（FGA `user:X admin tenant:5`） | `/model/manage` → "添加模型" | DB `tenant_id=5`；audit_log `operator_tenant_id=5` |
| §8 | Child Admin | 尝试编辑 Root 共享模型（直接 curl PUT） | HTTP 403 + body `status_code=19801` |
| §11 | Child Admin | `/model/manage` 右上 "系统模型设置" 按钮 | 按钮不可见（仅超管 `user.role==='admin'`）|
| §13 | 超管 | 顶部 tabs 切 Child 5 | 列表变 Child 5 视图；`admin_scope:{user_id}` Redis key=5 |
| §16 | 运维 | v2.4 MySQL dump 导入 → `alembic upgrade head` | `llm_server.tenant_id` 默认=1（F001 已回填）；`uk_llm_server_tenant_name` 索引就位 |
| §17 | 超管 | `curl /api/v1/llm?only_shared=true` | 返当前已对 ≥1 个 Child 分发的 Root 模型列表（预览弹窗数据源） |

---

## 偏差与未完成项

见 [tasks.md §实际偏差记录](./tasks.md)：

1. **T03 依赖路径调整** — `_check_is_global_super` 替代未 shipped 的 `LoginUser.is_global_super()`（沿 F019 precedent）
2. **T11b 节点调用链** — 未触碰 workflow/assistant 代码，依赖 tenant_filter event 自动承担（降低 F020 blast radius）
3. **MountDialog UI 未新建** — T10 仅提供 `?only_shared=true` 数据端点，UI 集成挂至 F011 后续 PR（D8）
4. **TenantOption 列表简化** — T15b 仅 3 个 tab（Global/Root/leaf），未来可扩展为完整 Child 列表

---

## 下一步（T16 后续）

- [ ] 114 worktree 同步 + 执行「执行清单」4 个小节
- [ ] 按「手工 QA」表逐项验证（建议 §3、§8、§11、§13 为最小可信冒烟）
- [ ] `/code-review --base 2.5.0-PM` 完整 L2 审查
- [ ] 合并回 `2.5.0-PM` + worktree 清理

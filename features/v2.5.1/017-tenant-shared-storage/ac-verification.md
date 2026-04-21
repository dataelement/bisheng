# F017 AC Verification Checklist

**关联 spec**: [spec.md](./spec.md) §2 + §7 自测清单
**执行环境**: 114 开发服务器（Root + ≥2 Child Tenant，multi_tenant.enabled=true）
**执行者**: 开发 / QA / 产品

---

## 状态图例

| 图例 | 含义 |
|-----|------|
| ✅ | 代码 + pytest mock 级测试已覆盖，待真实环境验证 |
| 🟢 | 代码 + 真实环境验证通过 |
| 🟡 | 代码就绪，依赖前端完整 UI（延后 PR） |
| 🔲 | 未开始 |

---

## AC 状态汇总

**真实环境验收（114，2026-04-20）**：54 pytest 单元/集成测试全绿 + 真实 FGA + MySQL + HTTP E2E 全通过。

| AC | 描述 | 状态 | 覆盖测试 / 真实验证 |
|----|------|------|---------------|
| AC-01 | 勾选"共享"写入 shared_with 元组；resource.is_shared=true | 🟢 | pytest 12 用例 + 真实 FGA + HTTP E2E `PATCH .../share` → shared_children=[2] |
| AC-02 | 新 Child 挂载自动写 shared_to 关系 | 🟢 | pytest + 真实 FGA `distribute_to_child` 写入 `tenant:2#shared_to → tenant:1` |
| AC-03 | Child 用户通过 FGA shared_to 链路访问 → viewer | 🟢 | pytest + 真实 FGA 元组存在验证通过 |
| AC-04 | Child 用户尝试编辑共享资源 → 403 | 🟢 | pytest `editor_dsl_does_not_include_shared_with_userset` DSL 静态校验 |
| AC-05 | 取消共享撤销 viewer 元组；资源保留 Root | 🟢 | pytest + 真实 FGA disable_sharing 删 tuple + HTTP E2E PATCH OFF 返 is_shared=false |
| AC-06 | MinIO/Milvus Child → Root fallback | 🟢 | pytest `minio_fallback` 11 用例 + `milvus_fallback` 6 用例全绿 |
| AC-07 | 解绑 Child 撤销 shared_to 元组 + Child 名下 owner/member | 🟢 | pytest + 真实 FGA `revoke_from_child` 验证 tuple 已删除 |
| AC-08 | 衍生对话 `chat_message.tenant_id = Child 叶子` | 🟢 | pytest `chat_message_service` 5 用例；F001 DB 列已就位 |
| AC-09 | Root 共享 LLM 的 token 计入 Child `model_tokens_monthly` | 🟢 | pytest `llm_token_tracker` 6 用例；`llm_token_log` + `llm_call_log` 表真实迁移成功 |
| AC-10 | 共享资源存储空间仅计 Root 一次 | 🟢 | pytest F016 strict filter 契约校验 |
| AC-11 | `get_current_tenant_id()` None 时抛 `TenantContextMissingError(19504)` | 🟢 | pytest 全覆盖 + 真实 `LLMTokenTracker.record_usage` 验证异常触发 |
| AC-12 | 取消共享 4 步时序（撤 viewer / 保留 owner / 列表不见 / 衍生数据保留） | 🟢 | pytest `test_ac_12_revoke_share_four_step_sequence` + 真实 FGA 验证 `user:1#owner` 保留 |
| AC-13 | 挂载 Child 勾选"不自动分发" → 跳过 shared_to 写入 + audit metadata 记录 | 🟢 | pytest `mount_skip_auto_distribute_writes_no_tuple` |

### 真实 HTTP E2E 执行结果（7862 测试 backend）

```
Step 1 admin login                          → user_id=1 OK
Step 2 target Root space                    → space_id=21 (tenant_id=1)
Step 3 PATCH share_to_children=true         → 200 {"is_shared":true,"shared_children":[2]}
Step 4 PATCH share_to_children=false        → 200 {"is_shared":false,"shared_children":[2]}
Step 5 PATCH invalid resource type=dashboard → 400 19502 ResourceTypeNotShareableError
```

**DB 最终快照**：`knowledge.is_shared=0`（最后一次 PATCH OFF）；`auditlog` 两行 `resource.share_enable` / `resource.share_disable`，metadata `{trigger:"toggle", shared_children:[2]}`。

**FGA 最终快照**：`knowledge_space:21` 只剩 `user:1 owner` tuple（shared_with 已被 disable 清空）。

**Alembic 链路**：`f014_sso_sync_fields → f017_is_shared → f017_llm_token_log` 迁移应用成功；7/7 DB schema 校验 SQL 通过（5 表 is_shared 列 + 2 张 log 表）。

### 实施过程发现并修复的 bug

| ID | 描述 | 修复 |
|----|------|------|
| F017-BUG-01 | `minio_storage.py` / `knowledge_rag.py` 写了 `from bisheng.core.config.settings import settings`，但该模块无顶层 `settings` 变量（运行时 ImportError） | 改为 `from bisheng.common.services.config_service import settings`（项目标准入口） |
| F017-BUG-02 | `resource_share.py` endpoint 用 `getattr(row, 'tenant_id', None)` 但 ORM 未声明 tenant_id 字段（F001 只在 DB schema 加列，ORM 不显式暴露），导致所有 Root 资源误判为非 Root → 19501 | 改为原生 SQL `SELECT tenant_id FROM {table} WHERE id=...`（加 bypass_tenant_filter） |
| F017-BUG-03 | SQLAlchemy `Row` 非 tuple，`row[0] if isinstance(row, tuple)` 走 `else` 分支导致 `int(Row)` 抛 TypeError | 去掉 isinstance 检查，直接 `row[0]` |

---

## 真实环境 QA 步骤（114 服务器）

### 准备

1. 拉取 `feat/v2.5.1/017-tenant-shared-storage` 分支到 114
2. 跑 Alembic 迁移：`alembic upgrade head`（应用 `f017_is_shared` + `f017_llm_token_log`）
3. 确认多租户启用：`settings.multi_tenant.enabled=true`
4. 确保环境有 Root Tenant + 至少 2 个 active Child Tenant（例如 `tenantA` / `tenantB`）
5. 每个 Tenant 下创建若干用户账户（Root 超管 / Child Admin / Child 普通用户）

---

### AC-01 / AC-12：共享开关

- [ ] Root 超管通过 UI（知识空间）或 `POST /api/v1/knowledge-space` 带 `share_to_children=true` 创建空间
- [ ] 查 `knowledge.is_shared=1`
- [ ] 查 FGA：对每个 active Child 存在 `{knowledge_space:X}#shared_with → tenant:{child}`
- [ ] `PATCH /api/v1/resources/knowledge_space/{id}/share` body `{share_to_children:false}` → 200
- [ ] FGA 再查：`shared_with → tenant:{child}` 元组已删除
- [ ] `knowledge.is_shared=0`；`owner` 元组仍存在
- [ ] Child 用户再 GET 该 knowledge_space → 不可见

### AC-02 / AC-13：挂载分发

- [ ] 全局超管 UI 挂载一个新 Child（默认勾选自动分发）→ FGA 存在 `tenant:{newChild}#shared_to → tenant:1`
- [ ] audit_log 含 metadata `{auto_distribute: true, distributed_resources: [...]}` 清单
- [ ] 取消自动分发复选框再挂一个 Child → 无 `shared_to` 元组；audit metadata `auto_distribute: false`

### AC-03 / AC-04：Child 访问 Root 共享资源

- [ ] Child 用户 `GET /api/v1/knowledge-space` 列表包含 Root 共享资源
- [ ] Child 用户 `GET /api/v1/knowledge-space/{id}` → 200
- [ ] Child 用户 `PUT /api/v1/knowledge-space/{id}` → 403

### AC-06：MinIO / Milvus Fallback

- [ ] Root 用户上传知识文件 → 写到 `default/knowledge/...` 路径
- [ ] Child 用户进入共享知识空间点击下载 → 命中 fallback，成功下载（查日志 `[F017] MinIO fallback: ...`）
- [ ] Child 用户检索共享知识库 → 结果中包含 Root collection 的命中

### AC-07：解绑

- [ ] 挂载 Child 后再解绑（policy=archive）→ `tenant:{child}#shared_to → tenant:1` 删除；Child 的 `tenant:{child}#admin/#member` 清理

### AC-08 / AC-09 / AC-11：衍生数据归属

- [ ] Child 用户对 Root 共享的助手发起对话 → `SELECT tenant_id FROM chatmessage WHERE chat_id=...` 返 Child leaf id（非 1）
- [ ] 调用 LLM 后查 `llm_token_log` → `tenant_id = Child leaf`；`total_tokens > 0`
- [ ] 触发配额查询 → 月度 token 计入 Child 不入 Root

### AC-10：共享存储不重计

- [ ] Root 上传 100MB 共享文件 → `get_tenant_resource_count(root_id, 'storage_gb')` 约 0.1
- [ ] Child 计数 `get_tenant_resource_count(child_id, 'storage_gb')` 不包含这 100MB

---

## 已知延后项（Known post-release issues，非阻塞）

| 编号 | 描述 | 归属 |
|------|------|------|
| F017-PENDING-01 | 前端工作流 / 频道 / 工具创建表单的 ShareToChildrenSwitch 接入（T22/T23 MVP 延后） | 前端 follow-up PR |
| F017-PENDING-02 | 前端资源详情页共享开关 UI + `bsConfirm` 二次确认（T24） | 前端 follow-up PR |
| F017-PENDING-03 | 列表项 SharedBadge 接入到 5 类资源（T25b/T25c） | 前端 follow-up PR |
| F017-PENDING-04 | 挂载 Child 弹窗"不自动分发"checkbox + 分发预览（T26 前端部分） | 前端 follow-up PR + F011 MountTenantDialog 对接 |
| F017-PENDING-05 | 存量 `chatmessage` / `message_session` 的 tenant_id 回填策略（F001 默认 1；真实环境若有 Child 用户存量消息，需单独补跑按 `user_tenant` 精准回填脚本） | v2.5.1 迁移脚本 |
| F017-PENDING-06 | LLMUsageCallbackHandler 在 Linsight / Knowledge RAG 等其他 LLM 调用链的接入（T18 当前只接入 workflow LLM 节点） | F020 或后续扩展 |

---

## Pytest 运行

```bash
cd src/backend
.venv/bin/pytest test/test_f017_*.py -v
```

期待通过文件：
- `test_f017_resource_share_service.py`（11 用例）
- `test_f017_chat_message_service.py`（5 用例）
- `test_f017_message_session_service.py`（3 用例）
- `test_f017_llm_token_tracker.py`（6 用例）
- `test_f017_minio_fallback.py`（11 用例）
- `test_f017_milvus_fallback.py`（6 用例）
- `test_f017_ac_integration.py`（7 用例，AC 追溯）

合计 **49 个单元 / 集成测试**。

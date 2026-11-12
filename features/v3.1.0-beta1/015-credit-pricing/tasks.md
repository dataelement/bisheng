# Tasks: 积分按模型真实价格扣除

**关联规格**：[spec.md](./spec.md)
**版本**：v3.1.0-beta1（F015-credit-pricing）
**分支**：bisheng `feat/3.1.0-beta1-015-credit-pricing`；bisheng-desktop `feat/v130-credit-pricing`（S8 再建）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户 2026-11-12 确认；AC-22 与两条边界仍待产品确认，先按推荐实现 |
| design.md | ✅ 已评审 | 用户 2026-11-12 确认；决策 4、6、16、18 的产品确认项先按推荐实现 |
| test-cases.md | ✅ 已生成 | QA 参考，不作为开发门禁 |
| runbook.md | 🔲 草稿 | 停服时长待演练实测 |
| tasks.md | 🔲 草稿 | |
| 实现 | 🔄 进行中 | 17 / 36 |

---

## 开发模式

- **按 Wave 推进**：Wave 内无依赖的任务可并行；每个任务标 `依赖:`。
- **后端 Test-First**：先写测试并跑一次确认失败，再实现。纯函数（算价、换算、倍率、口径）用逐位算例断言；token 口径用真实返回体夹具。
- **两组回归**：每个阶段结束跑 A 组（不连真实库，范围见基线）和 B 组（真实库专项：本机 Docker MySQL 8 + Redis 7，`DSH_TEST_DATABASE_URL` / `DSH_TEST_DATABASE_ISOLATED=1` / `DSH_TEST_REDIS_URL` / `DSH_TEST_REDIS_ISOLATED=1`，库名以 `dsh_test_` 开头且需预建 `user` 表），逐条与基线对比，新失败必须为 0。
- **前端**：platform `vitest run`、client `jest`、packages/ui `tsc --noEmit`；改动文件 ≤ 600 行；联调在测试服务器手动验证。
- **自包含任务**：设计论证指向 design.md，不在此复制。
- **不做的事**：推送、开 PR、改测试服务器数据、执行升级手册任一步之前先问 Callum；不使用仓库级 git 写操作。

## 基线（改动前，2026-11-12，提交 3254ab555）

| 组 | 范围 | 结果 |
|---|---|---|
| A（不连真实库） | test/dsh test/llm test/database test/workstation test/channel test/common | 3,358 通过 / 73 失败 / 60 报错 / 234 跳过（2 分 34 秒）；明细 `/tmp/f015-baseline-a.xml`（本机） |
| B（真实库专项，Docker MySQL 8 + Redis 7） | test/dsh 中使用真实库的 12 个文件（`/tmp/f015-run-b.sh`，每次先重置库并预建 `user` 表） | 99 通过 / 52 失败 / 2 跳过；失败为 test_automatic_quota_recovery 44（该组在 A 组 sqlite 下通过）、test_model_quota 5（A 组同样失败）、test_policy_repository 2、test_migration_mysql 1（单独运行通过，混跑相互影响） |
| 前端 / 桌面 | platform、client、packages/ui、desktop enterprise | 进入 S6 / S8 前补跑 |

---

## Tasks

### Wave 0 — 文档（S1）

- [ ] **T00**: SDD 文档与版本契约
  **文件**: 本目录 request / spec / design / runbook / tasks；`features/v3.1.0-beta1/release-contract.md`
  **逻辑**: spec、design 经用户确认（★）；design 确认后按模板生成 test-cases.md；release-contract 登记领域归属、依赖、错误码
  **依赖**: 无

### Wave 1 — 模型价格（S2，llm 模块）

- [x] **T01**: 价格结构 ModelPricing
  **文件**: `src/backend/bisheng/llm/domain/pricing/schemas.py`、`__init__.py`
  **逻辑**: 十进制字符串校验（≤ 6 位小数、上限 999999.999999）、`extra="forbid"`、`cache_write` 可空、`revision ≥ 1`（design §4.2）
  **测试**: `test/llm/test_model_pricing_catalog.py`（结构部分）
  **覆盖 AC**: AC-08, AC-09
  **依赖**: T00

- [x] **T02**: 内置价格表与精确匹配
  **文件**: `src/backend/bisheng/llm/domain/pricing/catalog.py`、`catalog.json`
  **逻辑**: 加载时校验 key 重复、同提供方别名重复、价格格式；normalize 只去空格转小写，不去日期后缀；`openai_compatible` 按名称匹配并返回 `via_name`；条目无分时段 / 分档字段，带 `source_url`、`verified_at`
  **测试**: `test/llm/test_model_pricing_catalog.py`（约 18 个）
  **覆盖 AC**: AC-08, AC-09
  **依赖**: T01

- [x] **T03**: 保存时补价与 revision 比较交换
  **文件**: `src/backend/bisheng/llm/domain/pricing/service.py`；`llm/domain/services/llm.py`（add / update 各一处调用）；`llm/domain/models/llm_server.py`（`update_server_with_models` 事务内校验 revision）
  **逻辑**: 新模型无价 → 匹配或 0（DEFAULT）；带价 → 服务端判定来源；已有模型无价 → 保留；已有模型带价 → revision 相等才写并 +1，否则冲突（design 决策 17）
  **测试**: `test/llm/test_model_pricing_save.py`（约 16 个，含并发保存、非 LLM 不受影响、`model_token_config_upgrade.py` 保留 pricing）
  **覆盖 AC**: AC-08, AC-09, AC-10
  **依赖**: T02

- [ ] **T04**: 改价入口与三个接口（单一写入边界）
  **文件**: `src/backend/bisheng/llm/api/pricing.py`、llm 路由注册；`llm/domain/services/llm.py`（`update_model_pricing`）；`llm/domain/repositories/model_pricing_repository.py`；`common/errcode/llm.py`（10813 价格冲突）
  **逻辑**: Root 只读（19801）→ 提供方行锁与空闲检查（优先复用 F118 `alock_provider` / `arequire_idle`；F118 未合入时对 `llm_model` 行 `with_for_update()`）→ 租户校验 → revision 比较交换，只改 `config.pricing` → 提交后清本进程缓存、写审计
  **测试**: `test/llm/test_price_catalog_api.py`（约 10 个）
  **覆盖 AC**: AC-08, AC-10
  **依赖**: T03；F118 合并顺序确认

### Wave 2 — 计费核心与口径（S3，dsh 模块）

- [x] **T05**: 积分设置表、仓储、租户登记
  **文件**: `src/backend/bisheng/dsh/domain/models/credit_setting.py`、`dsh/domain/repositories/credit_setting.py`、`core/database/tenant_filter.py`
  **逻辑**: 无行返回默认值、不缓存；PUT 带 version，冲突 `DshOperationConflictError`；审计 `UnifiedPolicyAudit(resource="credit-settings")`；登记 `_TENANT_AWARE_MODEL_MODULES`
  **测试**: `test/dsh/test_credit_settings.py`（约 14 个）、`test/database/test_tenant_aware_credit_setting.py`（约 3 个）
  **覆盖 AC**: AC-05, AC-16, AC-20
  **依赖**: T00

- [x] **T06**: 快照与算价
  **文件**: `src/backend/bisheng/dsh/domain/schemas/pricing.py`、`dsh/domain/services/pricing.py`；`common/errcode/dsh.py`（26176）
  **逻辑**: 精简快照（design 决策 19）；缺失 → 26176；换算向上取整；`price_usage` 两个结果 ≤ 2⁶³−1
  **测试**: `test/dsh/test_pricing_snapshot.py`（约 24 个，含 AC-01 原例逐位）
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-22
  **依赖**: T01, T05

- [x] **T07**: UsageEvent 带快照
  **文件**: `src/backend/bisheng/dsh/domain/schemas/usage.py`
  **逻辑**: `pricing` 可选；`billed_tokens` 有快照按新算法、无快照按旧公式；`cost_micro`、`currency`；溢出按用量异常处理
  **测试**: `test/dsh/test_pricing_ledger_replay.py`（部分）
  **覆盖 AC**: AC-01, AC-04, AC-07
  **依赖**: T06

- [x] **T08**: 两个入口不经缓存取价
  **文件**: `src/backend/bisheng/dsh/runtime.py`、`dsh/domain/services/chat_credits.py`、`dsh/domain/services/model.py`
  **逻辑**: `read_model_pricing`、`read_credit_setting` 按主键直读；替换 `chat_credits.py` 第 77 行与 `model.py` 第 175 行的 `credit_rate`；免费 → unmetered；`admit_round` 免费跳过 probe
  **测试**: `test/dsh/test_chat_credits.py`、`test/dsh/test_model_service.py` 补用例；`test/dsh/test_pricing_freshness.py`（约 4 个）
  **覆盖 AC**: AC-06, AC-10, AC-11, AC-22
  **依赖**: T06, T07

- [x] **T09**: 事件身份哈希
  **文件**: `src/backend/bisheng/dsh/infrastructure/quota_redis.py`
  **逻辑**: 有快照才加入哈希；历史事件向量哈希不变
  **测试**: `test/dsh/test_pricing_ledger_replay.py`
  **覆盖 AC**: AC-07
  **依赖**: T07

- [x] **T10**: 落库与对账恢复
  **文件**: `src/backend/bisheng/dsh/domain/models/model_call.py`、`dsh/domain/repositories/usage.py`
  **逻辑**: 三列（pricing 用 `JsonType`）；`project_batch` 快照不可变（规范化比较）、写花费与币种；`recovery_snapshot` 第 201 行改为由事件重算
  **测试**: `test/dsh/test_pricing_ledger_replay.py`（约 12 个）；`test_usage_repository.py`、`test_unified_credit_ledger.py` 补用例
  **覆盖 AC**: AC-04, AC-07
  **依赖**: T07, T11

- [x] **T11**: Alembic 迁移
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_1_0b1_f015_dsh_call_pricing.py`
  **逻辑**: `down_revision` 取 `uv run alembic heads` 唯一结果；三列可空，守卫同 `v3_0_0_f111_matched_words.py`
  **测试**: `test/database/test_alembic_f015_call_pricing.py`（sqlite + MySQL）；`test_alembic_single_head.py`
  **覆盖 AC**: AC-07, AC-20
  **依赖**: T00

- [x] **T12a**: 统一 token 口径
  **文件**: `src/backend/bisheng/dsh/infrastructure/usage_contract.py`、`chat_adapter.py`、`responses_adapter.py`
  **逻辑**: design §4.4 映射；两个适配器经它输出
  **测试**: `test/dsh/test_usage_contract.py`（逐来源夹具，普通与流式）
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T00

- [x] **T12b**: Anthropic 分桶缓存写入
  **文件**: 同 T12a
  **测试**: 用 `langchain-anthropic` 1.4.7 生成的 `usage_metadata` 夹具
  **覆盖 AC**: AC-02
  **依赖**: T12a

- [x] **T12c**: 违反不变式的纠正与打点
  **文件**: 同 T12a
  **逻辑**: 缓存 > 输入时按排他口径加回、打点并告警（边界规则待产品确认，确认结果不同时只改这一处）
  **覆盖 AC**: AC-02
  **依赖**: T12a

### Wave 3 — 范围、出口、删旧、升级（S4）

- [x] **T13**: 知识空间问答计费
  **文件**: `src/backend/bisheng/dsh/domain/services/chat_credits.py`（`governed`）
  **测试**: `test/dsh/test_billing_scope.py`
  **覆盖 AC**: AC-14, AC-21
  **依赖**: T08

- [x] **T14**: 频道问答看图
  **文件**: `src/backend/bisheng/channel/domain/services/channel_chat_service.py`（第 164 行）
  **测试**: `test/dsh/test_billing_scope.py`
  **覆盖 AC**: AC-14
  **依赖**: T13

- [x] **T15**: 回答溯源扣但不拦
  **文件**: `chat_credits.py`（公开 `unmetered()`）、`llm/domain/services/llm.py`（`get_knowledge_source_llm(_async)` 加 `app_type`）、`common/chat/utils.py`、`workstation/domain/services/chat_helpers.py`（第 92 行）
  **测试**: `test/dsh/test_billing_scope.py`、`test/dsh/test_chat_credits_unmetered.py`
  **覆盖 AC**: AC-14, AC-15
  **依赖**: T08

- [x] **T16**: 倍率出口
  **文件**: `dsh/domain/services/pricing.py`（`pricing_hints`）、`dsh/domain/services/model_catalog.py`、`dsh/domain/services/model.py`（`list_models`）、`workstation/api/endpoints/config.py`、`dsh/api/endpoints/credit_pricing.py`、`dsh/api/router.py`
  **测试**: `test/dsh/test_pricing_hints.py`（约 10 个）
  **覆盖 AC**: AC-12, AC-13, AC-19
  **依赖**: T05, T06

- [ ] **T17**: 删除旧倍率
  **文件**: `dsh/domain/schemas/unified_policy.py`、`dsh/domain/repositories/unified_policy.py`、`dsh/domain/schemas/model_policy.py` 及约 7 个已有测试
  **逻辑**: `credit_multiplier` 入参接受并忽略；不再读写 `credit_rate`；列与 f062 迁移保留
  **覆盖 AC**: AC-17
  **依赖**: T08

- [ ] **T18**: 升级脚本与门禁
  **文件**: `src/backend/scripts/backfill_model_pricing.py`、`.sh`
  **逻辑**: 预检 / `--apply` / `--check`；遍历全部租户；幂等
  **测试**: `test/llm/test_backfill_model_pricing.py`（约 8 个）
  **覆盖 AC**: AC-18
  **依赖**: T03, T11

- [ ] **T18a**: 升级手册与发版说明
  **文件**: 本目录 `runbook.md`
  **依赖**: T18

- [ ] **T18b**: 迁移演练脚本与 MySQL 演练
  **文件**: `src/backend/scripts/rehearse_dsh_call_pricing_migration.py`
  **逻辑**: 造 100 万 / 1,000 万行 → 迁移计时 → JSON 往返 → 降级再升级；MySQL 本机执行，达梦请同事执行（PR-1 合并前置）
  **覆盖 AC**: AC-20
  **依赖**: T11

- [ ] **T18c**: Redis 容量复测
  **逻辑**: 真实准入、结算、投影确认流程测每次调用占用，替换 runbook 的模拟数字
  **依赖**: T10

### Wave 4 — 管理后台（S6）

- [ ] **T19**: 类型与接口层 — `types/dsh.ts`、`controllers/API/modelPricing.ts`、`dshUnified.ts` · 覆盖 AC: AC-10, AC-17 · 依赖: T16
- [ ] **T20**: 价格区组件 — `ModelPriceFields.tsx`、`modelPricing.ts` · 覆盖 AC: AC-08, AC-09 · 依赖: T19
- [ ] **T21**: 添加 / 编辑模型接入价格区 — `ModelItem.tsx` · 覆盖 AC: AC-08, AC-09 · 依赖: T20
- [ ] **T22**: 保存 — `modelSavePayload.ts`、`ModelConfig.tsx`（降到 600 行内；只在价格改过时提交，带 revision） · 覆盖 AC: AC-10 · 依赖: T21
- [ ] **T23**: 用户可选模型表 — `UserSelectableModels.tsx`、`dsh/ModelPriceDialog.tsx`、`dsh/BaseModelPicker.tsx` · 覆盖 AC: AC-10, AC-12, AC-13, AC-22 · 依赖: T19
- [ ] **T24**: 积分设置 — `SystemPage/dsh/CreditSettingsPanel.tsx`、`SystemPage/dsh/index.tsx` · 覆盖 AC: AC-05, AC-16 · 依赖: T19
- [ ] **T25**: 删除旧倍率输入与文案 — `dsh/ModelMultiplierInput.tsx`（删）、`ModelAccessDialog.tsx`、三语文案 · 覆盖 AC: AC-17 · 依赖: T23

### Wave 5 — 网页工作台与组件库（S7）

- [ ] **T26**: Cascader 可选 suffix / footer — `packages/ui/src/components/Cascader/*` · 依赖: 无（需组件库负责人认可）
- [ ] **T27**: 模型下拉框倍率 — `client/src/types/chat/config.ts`、`components/Chat/AiModelSelect.tsx` · 覆盖 AC: AC-13 · 依赖: T16, T26

### Wave 6 — 桌面（S8，bisheng-desktop）

- [ ] **T28**: 契约与错误文案 — `contract.js`、`contract.d.ts`、`enterprise-service.ts`、`error-copy.js` · 覆盖 AC: AC-13, AC-19, AC-22 · 依赖: T16
- [ ] **T29**: 账号页倍率 — `client.js renderModelRow` · 覆盖 AC: AC-13 · 依赖: T28
- [ ] **T30**: Work 下拉框插槽（priority −1） — `client.js` · 覆盖 AC: AC-13 · 依赖: T28
- [ ] **T31**: 桌面测试 — `test/enterprise-contract.test.ts`、`test/enterprise-model-label.test.mjs`、`test/enterprise-model-sync.test.mjs` · 依赖: T28–T30

### Wave 7 — 联调验收（S9）

- [ ] **T32**: 测试服务器停服升级与逐条验收（需 Callum 同意每一步）
  **逻辑**: 按 runbook 全流程并记录耗时；按验收清单逐条核对扣费；结果写 validation.md、e2e-checklist.md
  **覆盖 AC**: AC-01 – AC-22
  **依赖**: PR-1、PR-2 部署到测试服务器

---

## 实际偏差记录

- T01 测试放在 `test/llm/test_model_pricing_schema.py`（与价格表测试分开），不影响 AC 追溯。
- T06 错误码 26176 定为 HTTP 503 / `service_unavailable_error`：未升级的旧桌面按通用「暂不可用」展示（AC-19），见 design §6.1。
- T07 用量超出 int64 时在 `DshModelService.settle_usage` 结算为用量未知（`usage_out_of_range`），不让结算报错。
- T11 降级（downgrade）拒绝执行而不是删列，与仓库 DSH 迁移惯例（f111）及 runbook「回滚靠备份恢复」一致 → design 决策 18。
- 新增 26176 时补了共享文案包 `packages/locales/src/api_errors/*.json` 并用 `node scripts/build.mjs` 生成 platform、client 产物（由 `test_error_code_uniqueness` 强制）。
- T08 桌面入口直接用 `model_loader` 加载的模型取价（该路径本就不经缓存），未另读价格；网页入口经 `LLMService.read_model_pricing` → `ModelPricingRepository` 直读。收费模型调用 `check_and_start` 时不传 `mode`，与原调用方式一致，只有免费模型传 `unmetered`。
- T08 现有测试夹具的假模型补了与旧 1 倍等价的价格（`test/dsh/pricing_fixtures.py`），原断言不变；`test_work_admission_snapshots_model_multiplier` 改写为按价格快照断言（旧倍率被删除，AC-17）。
- T12 口径校验放在结算时对整次调用的累计用量做一次（`enforce_inclusive`），字段映射在每条消息归一化时做，避免流式分片误判。
- T02 价格表在首次使用时加载并校验，随包文件的有效性由 `test_model_pricing_catalog` 保证，未在应用启动钩子里加载（避免改动 main.py）。智谱、MiniMax 只有国际站美元价，只映射 `openai_compatible`，不映射国内 `zhipu` / `minimax` 类型。
- T03 新增错误码 10814（价格格式无效，已登记 release-contract）。revision 比较目前在服务层基于保存前读取的旧值做；事务内加锁复查随 T04 与 F118 的锁方案一起完成。
- T15 偏离：`common/` 不能依赖领域层，所以免检标记不在 `process_source_document` 里设置，而是由工作台在 `chat_credits.unmetered()` 内创建溯源任务（任务继承上下文）。新增决策 20：溯源、看图模型标记 `admin_selected`，照常计费但不受员工可选模型范围限制 → design 决策 20、坑 16–17。
- T16 基准模型取积分设置的 base_model_id，未设置时取工作台日常对话默认模型；基准不在线、被删除、缺价或免费时所有倍率为 null。桌面 `/dsh/models` 经注入的 `hint_context_reader` 计算倍率（测试中不注入时不返回该字段）。
- 发现原有失败（不在本特性范围）：`test/api/test_route_path_naming.py` 在改动前即因 `/api/v2/workstation/config/knowledge` 失败。
- 发现仓库原有测试隔离缺陷（不在本特性范围，未改）：`test/dsh/test_policy_repository.py` 的 `sql_store` 夹具在 `[external]` 参数缺少真实库时于 setup 中途失败，留下「已初始化但只登记部分表」的租户过滤状态，导致之后混跑的租户隔离用例误报（基线中 `test_unified_policy_repository` 的失败即此原因）。`test_credit_settings` 夹具已显式登记所需表以免受影响。

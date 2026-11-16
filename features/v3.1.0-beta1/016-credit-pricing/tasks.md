# Tasks: 积分按模型真实价格扣除

**关联规格**：[spec.md](./spec.md)
**版本**：v3.1.0-beta1（F016-credit-pricing）
**分支**：bisheng `feat/3.1.0-beta1-016-credit-pricing`；bisheng-desktop `feat/v130-credit-pricing`（S8 再建）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户 2026-11-12 确认；AC-22 与两条边界仍待产品确认，先按推荐实现 |
| design.md | ✅ 已评审 | 用户 2026-11-12 确认；决策 4、6、16、18 的产品确认项先按推荐实现 |
| test-cases.md | ✅ 已生成 | QA 参考，不作为开发门禁 |
| runbook.md | 🔄 部分实测 | MySQL 与 Redis 已实测；达梦与全流程待执行 |
| tasks.md | 🔲 草稿 | |
| 实现 | 🔄 进行中 | 40 / 41（T26 不做；T04 已恢复并完成；T33–T37 为联调后新增；本机自测完成，剩 T32 测试服务器验收） |

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
| A（不连真实库） | test/dsh test/llm test/database test/workstation test/channel test/common | 3,358 通过 / 73 失败 / 60 报错 / 234 跳过（2 分 34 秒）；明细 `/tmp/f016-baseline-a.xml`（本机） |
| B（真实库专项，Docker MySQL 8 + Redis 7） | test/dsh 中使用真实库的 12 个文件（`/tmp/f016-run-b.sh`，每次先重置库并预建 `user` 表） | 99 通过 / 52 失败 / 2 跳过；失败为 test_automatic_quota_recovery 44（该组在 A 组 sqlite 下通过）、test_model_quota 5（A 组同样失败）、test_policy_repository 2、test_migration_mysql 1（单独运行通过，混跑相互影响） |
| 前端 platform | ModelPage + SystemPage/dsh；全量 vitest | 局部 423：420 通过 / 3 失败（ContentSafetyDetails ×2、ModelAccessDialog 1）；全量 15 个文件 40 个失败（approvalPage、hostedApp、dshRequestError 等，与本特性无关）；`pnpm lint` 原本就因 `ModelConfig.limit.test.tsx` 的中文字符串失败 |
| 客户端 | client、packages/ui | 进入 S7 前补跑 |
| 桌面（bisheng-desktop，origin/V1.3.0 9c410423） | `vitest run` 全量 | 未构建时 3,605 条：54 失败 + 3 个文件加载失败，均因缺少构建产物（PPT、Office、Word 模板）或需真实 Harness；`npm run build` 后全部通过 |

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

- [x] **T04**: 改价入口与三个接口（单一写入边界）【2026-11-13 恢复并完成，见偏差记录】
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
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_1_0b1_f016_dsh_call_pricing.py`
  **逻辑**: `down_revision` 取 `uv run alembic heads` 唯一结果；三列可空，守卫同 `v3_0_0_f111_matched_words.py`
  **测试**: `test/database/test_alembic_f016_call_pricing.py`（sqlite + MySQL）；`test_alembic_single_head.py`
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

- [x] **T17**: 删除旧倍率
  **文件**: `dsh/domain/schemas/unified_policy.py`、`dsh/domain/repositories/unified_policy.py`、`dsh/domain/schemas/model_policy.py` 及约 7 个已有测试
  **逻辑**: `credit_multiplier` 入参接受并忽略；不再读写 `credit_rate`；列与 f062 迁移保留
  **覆盖 AC**: AC-17
  **依赖**: T08

- [x] **T18**: 升级脚本与门禁
  **文件**: `src/backend/scripts/backfill_model_pricing.py`、`.sh`
  **逻辑**: 预检 / `--apply` / `--check`；遍历全部租户；幂等
  **测试**: `test/llm/test_backfill_model_pricing.py`（约 8 个）
  **覆盖 AC**: AC-18
  **依赖**: T03, T11

- [x] **T18a**: 升级手册与发版说明
  **文件**: 本目录 `runbook.md`
  **依赖**: T18

- [x] **T18b**: 迁移演练脚本与 MySQL 演练（达梦部分改由发版前统一回归覆盖）
  **文件**: `src/backend/scripts/rehearse_dsh_call_pricing_migration.py`
  **逻辑**: 造 100 万 / 1,000 万行 → 迁移计时 → JSON 往返 → 降级再升级；MySQL 本机执行，达梦请同事执行（PR-1 合并前置）
  **覆盖 AC**: AC-20
  **依赖**: T11

- [x] **T18c**: Redis 容量复测
  **逻辑**: 真实准入、结算、投影确认流程测每次调用占用，替换 runbook 的模拟数字
  **依赖**: T10

### Wave 4 — 管理后台（S6）

- [x] **T19**: 类型与接口层 — `types/dsh.ts`、`controllers/API/modelPricing.ts`、`dshUnified.ts` · 覆盖 AC: AC-10, AC-17 · 依赖: T16
- [x] **T20**: 价格区组件 — `ModelPriceFields.tsx`、`modelPricing.ts` · 覆盖 AC: AC-08, AC-09 · 依赖: T19
- [x] **T21**: 添加 / 编辑模型接入价格区 — `ModelItem.tsx` · 覆盖 AC: AC-08, AC-09 · 依赖: T20
- [x] **T22**: 保存 — `modelSavePayload.ts`、`ModelConfig.tsx`（降到 600 行内；只在价格改过时提交，带 revision） · 覆盖 AC: AC-10 · 依赖: T21
- [x] **T23**: 用户可选模型表 — `UserSelectableModels.tsx`、`dsh/ModelPriceDialog.tsx`、`dsh/BaseModelPicker.tsx` · 覆盖 AC: AC-10, AC-12, AC-13, AC-22 · 依赖: T19
- [x] **T24**: 积分设置 — `SystemPage/dsh/CreditSettingsPanel.tsx`、`SystemPage/dsh/index.tsx` · 覆盖 AC: AC-05, AC-16 · 依赖: T19
- [x] **T25**: 删除旧倍率输入与文案 — `dsh/ModelMultiplierInput.tsx`（删）、`ModelAccessDialog.tsx`、三语文案 · 覆盖 AC: AC-17 · 依赖: T23

### Wave 5 — 网页工作台与组件库（S7）

- [~] **T26**: Cascader 可选 suffix / footer — `packages/ui/src/components/Cascader/*` · 依赖: 无（需组件库负责人认可）
- [x] **T27**: 模型下拉框倍率 — `client/src/types/chat/config.ts`、`components/Chat/AiModelSelect.tsx` · 覆盖 AC: AC-13 · 依赖: T16, T26
- [x] **T34**: 「选择模型」用价格表兜底（2026-11-13 Callum 联调提出）— 服务商列表拉取失败时列出价格表里该类型的模型并保留失败原因；「OpenAI 兼容」新增按钮直接从价格表选 — `platform/.../ModelDiscovery.tsx`、`modelDiscoveryCatalog.ts`、`modelDiscoveryErrors.ts`（从 ModelDiscovery 拆出以守住 600 行） · 依赖: T02
- [x] **T35**: 客户端常驻剩余积分（2026-11-13 Callum 联调提出）— 网页工作台左下角 `client/src/components/dsh/SidebarCredits.tsx`；桌面左下角账号行 `bisheng-desktop packages/dsh-desktop-settings`，对话结束后自动刷新 · 依赖: T33
- [x] **T36**: 价格表重建（2026-11-16 Callum 提出：要更全、按厂商分类、收各家最新模型）— `llm/domain/pricing/catalog.json` 改为 13 家 87 个模型，版本 2026-11-16；`catalog.py` 名称没有条目时去掉中转站的厂商前缀再匹配；「选择模型」弹框按厂商分组、按厂商筛选、每行显示价格；百炼、方舟、千帆、TokenHub、硅基流动这类转售平台拉不到列表时列出全部厂商（自家在前），别家模型按名字带出官方价并提示核对（Callum 11-16 提出） `platform/src/pages/ModelPage/manage/ModelDiscovery.tsx`、`modelDiscoveryCatalog.ts`。取价规则和待复核清单见 `price-catalog.md` · 依赖: T34
- [x] **T37**: 额度用完后加额度「看不到变化」（2026-11-16 Callum 联调提出）— 员工端显示「剩余 / 额度」：网页左下角 `client/src/components/dsh/SidebarCredits.tsx`、桌面账号行 `bisheng-desktop packages/dsh-desktop-settings`（不限额显示「积分不限」）；后台改用户额度时预览「本月已用、保存后剩余」`platform/src/pages/SystemPage/dsh/CreditRulePreview.tsx`，后端 `GET /dsh/admin/users/{id}/credits` 加可选 `monthly_credits`、`enabled` 预览参数（按用户 / 部门 / 角色取最高的同一规则计算，不写库）；用量页用户卡片显示透支 · 依赖: T33、T35
- [x] **T33**: 本月积分展示（2026-11-13 Callum 联调时提出：界面上看不到员工的积分）— 网页「设置 → 客户端」积分卡片 `client/src/components/dsh/DshCreditsCard.tsx`、`DshDesktopPanel.tsx`（读已有的 `/dsh/me/credits`）；后台「用量」按用户显示本月已用 / 额度 / 剩余 `platform/src/pages/SystemPage/dsh/UserCreditsCard.tsx`、`PolicyView.tsx`，新接口 `GET /dsh/admin/users/{id}/credits`（与 `/me/credits` 共用 `month_credits`）；「当前时段已消耗」改为最多 2 位小数 · 依赖: 无

### Wave 6 — 桌面（S8，bisheng-desktop）

- [x] **T28**: 契约与错误文案 — `contract.js`、`contract.d.ts`、`enterprise-service.ts`、`error-copy.js` · 覆盖 AC: AC-13, AC-19, AC-22 · 依赖: T16
- [x] **T29**: 账号页倍率 — `client.js renderModelRow` · 覆盖 AC: AC-13 · 依赖: T28
- [x] **T30**: Work 下拉框插槽（priority −1） — `client.js` · 覆盖 AC: AC-13 · 依赖: T28
- [x] **T31**: 桌面测试 — `test/enterprise-contract.test.ts`、`test/enterprise-model-label.test.mjs`、`test/enterprise-model-sync.test.mjs` · 依赖: T28–T30

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
- T17 偏离：`DshModelPolicyState.credit_rate` 保留（它随策略快照进入对账恢复载荷，改结构有风险），计费已不读取；可见范围接口不再返回、不再写入旧倍率，`credit_multiplier` 入参照收但忽略（老后台兼容）。数据库列与 f062 迁移保留。
- T18b MySQL 部分完成（见 validation.md），达梦部分待同事环境，任务保持未勾选。
- T04 中两个只读接口 `GET /api/v1/llm/price-catalog`、`GET /api/v1/llm/price-catalog/match` 已实现（不涉及写入锁，添加模型时预填需要）；只有写入接口 `PUT /api/v1/llm/models/{id}/pricing` 暂缓。
- 2026-11-12 Callum 决定：T04（价格弹框内直接改价）暂缓，不等 F118；价格继续通过「编辑模型提供方」修改（T03），前端价格弹框先做成只读并提供跳转。AC-10 中「在价格弹框里改价」一项待 T04 恢复后补齐。
- 2026-11-12 Callum 决定（同事确认仓库惯例）：不做本特性单独的达梦演练，达梦兼容由发版前统一回归覆盖；PR 合并不再以达梦演练为前置。
- 发现原有失败（不在本特性范围）：`test/api/test_route_path_naming.py` 在改动前即因 `/api/v2/workstation/config/knowledge` 失败。
- 发现仓库原有测试隔离缺陷（不在本特性范围，未改）：`test/dsh/test_policy_repository.py` 的 `sql_store` 夹具在 `[external]` 参数缺少真实库时于 setup 中途失败，留下「已初始化但只登记部分表」的租户过滤状态，导致之后混跑的租户隔离用例误报（基线中 `test_unified_policy_repository` 的失败即此原因）。`test_credit_settings` 夹具已显式登记所需表以免受影响。
- T19 类型放在 `controllers/API/modelPricing.ts`（与接口函数同文件，平台惯例），未新建 `types/dsh.ts`。四个价格接口都带 `silent: true`，失败由页面就地提示，不弹全局错误。
- T22 保存时只提交改过的价格（与加载时的价格逐项比较，币种也比），没改的价格不随请求发送，服务端保留原值；这样修改模型名称、密钥等不会因为别人刚改过价格而报 10813 冲突。`ModelConfig.tsx` 由 617 行降到 587 行（校验逻辑移到 `modelSavePayload.ts`）。
- T23 价格弹框只读，按偏差记录中的决定实现；「去模型配置修改」做成弹框内的文字指引而不是直接跳转：用户可选模型表所在的「系统模型设置」页有未保存的显示名称等编辑，直接跳到服务提供方编辑页会丢失这些编辑，且跳转需要穿过三层组件传参。弹框在模型原价币种与计价币种不同时额外显示原价（新增文案 `dsh.pricing.originalPrice`）。
- T24 切换计价币种时的「保持预算 / 保持数字」二选一做成币种下方的单选项，而不是弹窗（表单内选择不适合用二次确认弹窗，Modal 组件也未定稿）；默认保持预算，按当前汇率换算到 6 位小数。积分设置的版本冲突（26130）显示「设置已被他人修改」。
- T25 删除 `ModelMultiplierInput` 及测试、`dshUnified` 的 `credit_multiplier` 字段与请求参数、三语文案 `dsh.unified.multiplier / multiplierHelp / multiplierInvalid / modelSettings`；`ModelAccessDialog` 本身未引用倍率，无需改动，只更新了它的测试。`ModelAccessDialog.test` 第一条用例改名后仍然失败，失败点与改动前相同（找不到 `subject.department` 按钮，界面已改为页签），不在本特性范围。
- S6 回归：ModelPage + SystemPage/dsh 463 条，460 通过 / 3 失败（与基线同 3 条）；platform 全量 15 个文件 40 个失败，在干净的基线提交上逐条一致（仅改名的那条名称不同）；`pnpm typecheck` 通过；本次改动的 26 个文件 eslint 无问题；`pnpm check-i18n` 通过。页面未在真实环境中查看（本机后端不是本分支），留到 S9 联调。
- S8 桌面在 bisheng-desktop 新 worktree `bisheng-desktop-f016/`、分支 `feat/v130-credit-pricing`（基于 origin/V1.3.0 9c410423，已去掉默认的上游跟踪以免误推集成分支），本地提交 85b6ab06，未推送。
- T28 偏离：26176 不改 `error-copy.js`（那是账号页登录类错误的文案表，26176 只会出现在模型调用里）；改为 `openai.js` 把 `model_pricing_missing` 列为平台错误码，并在 `dsh-client-ui-chat`、`dsh-client-ui-trajectory` 已有的「平台错误码本地化」补丁里各加一条中英文提示（沿用现有逐码映射的做法）。本机代理访问不了 lockfile 里的 npmmirror 地址，`patch-package` 自带的重新生成失败；改为按 patch-package 的 git 参数用干净原始包手工生成（先验证未改动时生成结果与已提交补丁只差一行陈旧的 index 哈希），再用 `patch-package --reverse` + 重新应用验证可完整撤销和重放。
- T30 偏离与风险：插槽是 single 类型，`priority: -1` 会遮住随包的 DeepSeek 1017 标签，仓库规范写明「不能为一个插件屏蔽其他贡献项」。为缩小影响，只在当前账号的模型目录带倍率提示时注册，未登录 / 旧服务端 / 没有企业模型时释放插槽；剩余代价是企业账号登录且同时用 DeepSeek 官方账号时 1017 标签不显示。已写入桌面仓库 `docs/patch-plugin-contract.md`，需在 PR 里请桌面负责人确认。倍率数据随现有前台目录刷新（启动、回到前台、账号变化）更新，不新增轮询。
- AC-13 中「桌面 Chat 模型下拉框」就是内嵌的网页工作台，由 S7（T27）覆盖，桌面不单独改。
- T31 测试：新增 `test/enterprise-model-label.test.mjs`（4 条：提示仓库只收当前账号、注册与释放、各类标签渲染、刷新后已挂载标签更新）；更新 `enterprise-contract`（合法 / 非法提示）、`enterprise-service`（登录 → 刷新 → 公开快照，且快照是副本）、`enterprise-package`（账号页倍率）、`enterprise-model-sync`（刷新结果交给调用方、卸载后不再回调；函数签名变化同步改了切片标记）、`enterprise-openai-adapter`（26176 分类）、`provider-error-patch`（两处补丁文案）。全量：`npm run build` 后 3,686 条，3,681 通过 / 0 失败 / 5 跳过；typecheck、`git diff --check` 通过。未做：真实 Harness 子进程与安装包里的 Work 下拉框 / 账号页目视验收（需要连接已升级的毕昇服务端）。
- T26 不做、T27 改法：共享 Cascader 的选项 `label` 只接受纯文本，加 suffix 要改组件库（需设计 / 组件库负责人认可）。改为把倍率拼在模型名后面的标签文字里（「Qwen Max · 3.00x」「· 1.00x 基准」「· 免费」），不改 `packages/ui`；搜索也会匹配这段文字。以后组件库支持 suffix 时可以换成灰色小字。新增三语文案 `modelPicker.ratioBase / ratioFree`；`types/chat/config.ts` 增加 `ModelPricingHint`。
- S7 检查：`AiModelSelect.test.tsx` 7 条通过（新增 1 条）；`src/components/Chat` + `modelRefresh` 共 200 条，190 通过 / 10 失败，失败在 `importFailureContract`、`ChatResourceMenu` 两个文件，在不含本次改动的干净副本上同样失败（与本特性无关）。本机 `canvas` 原生模块未编译导致 client jest 起不来，测试时用临时预加载脚本让 jsdom 视为未安装 canvas（不改仓库）。client typecheck、check-i18n 通过；改动文件 eslint 无问题，client 整体 lint 原本就因 `src/utils/failureInfo.ts` 失败。
- 2026-11-12 合并上游 feat/3.1.0-beta1（6a9255e3a，领先 350 个提交）：基线 3254ab555 处在上游一个缺陷的引入（f173bc70d）与修复（8efc7e6e7）之间，开启企业客户端时网页工作台对话直接报错（`runtime.sessions` 不存在），本机联调无法进行，因此先合并。冲突 8 个文件，处理见合并提交说明；迁移父节点改为上游最新头 `v310b1_merge_tenant_identity`；`ModelConfig.tsx` 上游已涨到 646 行，合并后再抽两段校验到 `modelSavePayload.ts`，降到 598 行。
- 2026-11-12 特性改号 015 → 016：上游已有 `015-knowledge-space-admin-ui`。目录、迁移 revision（`v310b1_f016_dsh_call_pricing`）、迁移文件与测试文件名、本特性新增内容里的编号一并改；上游 v2.5.1 的 F015（LDAP 校对）等引用不动。本地分支改名为 `feat/3.1.0-beta1-016-credit-pricing`。
- 合并后补的测试：上游 F009 让对账恢复读取用户归属租户与主部门，价格恢复测试补建这些数据（并按外键顺序写入）；上游新增的「入口不碰数据库」测试补上价格与积分设置的读取替身。
- 本机联调发现并修复三处界面问题（提交 030dd518a）：价格区在查到价格表前不显示状态；用户可选模型表最小宽度降到 1120；工作台与桌面 Work 下拉框里基准模型只显示「1.00x」。联调结果见 validation.md。
- T33 做法：员工端和后台用同一个计算（`unified_policy.month_credits`），金额是精确的小数字符串，前端只负责格式化（最多 2 位小数），不限额由服务端的 `unlimited` 标记表示。后台没有复用已有的 `GET /dsh/admin/users/{id}/policy`：该接口按 JS 安全整数校验额度，不限额用户的 int64 上限会让整份数据被判为格式错误；而且用户本月还没有调用时，它返回的「已用」是空，`/me/credits` 返回的是 0。积分卡片只在「按用户」查看时显示，按自然月统计，不随时间范围变化；页面右上「刷新」同时刷新积分。
- 发现原有缺陷（不在本特性范围，未改）：不限额用户（没有命中任何积分规则）有 2 个及以上模型时，读不到本月积分，`/dsh/me/credits` 和新的后台接口都返回 26126「额度状态暂不可用」，员工端和后台积分卡片显示「暂时无法读取」。原因：账本自动恢复（`automatic_quota_recovery.py` 第 182 行）把各模型额度直接相加，写入 Redis 的总额度。不限额时每个模型的额度都是 int64 上限，本机 f015admin 有 6 个模型，总额度为 55340232221128654842，超出 int64，`read_usage.lua` 因此判为 `bad_counter`。模型调用的准入只看单个模型的额度，所以调用本身不受影响。修复需要同时改恢复写入和 `read_usage.lua` 的总额度校验，属于统一额度账本，需要和账本负责人商量。
- T33 检查：client `components/dsh` jest 9 条通过（新增 3 条）；platform `dshPolicyView` 13 条通过（新增 5 条）；后端新增 `test/dsh/test_admin_user_credits.py` 3 条通过，同时跑的 `test_admin_api`、`test_self_service` 各有 1 条失败，与改动前的基线相同；两端 tsc-strict、check-i18n 通过，改动文件 eslint 和 ruff 无问题；arch-guard 通过。platform `SystemPage` + `ModelPage` 共 511 条，3 条失败：`ContentSafetyDetails` 2 条，在上游 6a9255e3a 上同样失败；`ModelAccessDialog` 1 条，见 T25。
- 2026-11-13 Callum 联调后要求在「用户可选模型」表里直接改价 → 恢复 T04。上游已合入 F118 的提供方写入锁（`model_provider_write_guard.alock_idle_model`），改价接口 `PUT /api/v1/llm/models/{id}/pricing` 照「改模型上下线」的写法加锁，锁内比较版本号并写入，只改 `config.pricing`，提交后清本进程缓存。审计记录未做（provider 保存原本也不写审计）。前端把「查看价格」弹框改为可编辑，复用添加模型时的价格区（带价格表比对和「恢复原价」），缺价模型也能在这里设价。AC-10 中「在价格弹框里改价」补齐。
- T34 说明：上游「选择模型」按 API Key 实时拉取服务商的模型列表，只有智谱、讯飞、MiniMax、腾讯 4 家有内置目录，「OpenAI 兼容」不在支持列表里，没有按钮。拉取失败（地址、Key、代理不对）时只显示错误。现在改为列出价格表里该类型的模型（OpenAI 8 个、OpenAI 兼容 37 个……），名称取价格表别名的第一项，提示管理员核对服务商实际使用的名称。导入的模型由价格区按名称带出价格。
- T35 说明与自测中发现的问题：桌面主进程缓存用量，内嵌网页 Chat 的调用不经过主进程，原来账号行不会更新。为此桌面本机刷新接口 `/api/enterprise.models.refresh` 增加可选 `{"includeUsage": true}`（broker 只放行这一个字段），账号行在 Chat 结束、打开菜单时读最新值，收到主进程其他通知时读本机缓存。新对话的标题生成是单独一次计费调用，比回答晚约 11 秒结算，所以网页和桌面都在对话结束后读两次（约 1.5 秒和 20 秒），网页另有 60 秒兜底。详细过程见 `self-test-2026-11-13.md`。
- T36 说明：旧表 37 条里千问 qwen-max / qwen-plus / qwen-flash 三个价格错用了新一代型号的价格，gpt-5.6-sol 已调价，智谱和 MiniMax 是国际站美元价；这次按官网重查。智谱、MiniMax 改为国内站人民币价，并加上 zhipu、moonshot、minimax、qianfan、tencent、spark 六种服务商类型，这些类型「选择模型」拉不到列表时也能退回价格表。日期后缀仍然不去（快照可能另有价格），只把豆包方舟常用的带日期型号逐个列为别名。已添加模型的价格不受影响（保存时才取价格表）。检查：后端 test/llm + test/dsh 与改动前同为 47 失败 / 61 报错，无新增，新增 7 条通过；platform 全量 69 条失败与改动前相同，`ModelDiscovery.test.tsx` 42 条通过（新增 1 条）；tsc 无新增错误；本机浏览器打开「OpenAI 兼容 → 选择模型」核对分组、筛选、价格，匹配接口核对带前缀名称。
- T37 说明：额度是每月上限，剩余 = 上限 − 本月已用，原逻辑就是这样；问题出在显示和透支。调用前只检查「已用 < 上限」，费用在调用结束后结算，单次调用可以透支（本机 f015user 一次调用约 929 积分：当时 DeepSeek 输入价被改成 100 元/百万、1 积分 = 0.01 元），透支后把额度改到低于已用，剩余仍是 0；员工端原来只显示剩余，看不出额度变了。这次只改显示和预览，不改额度分配和准入检查（与 design「非目标」一致）；调用前预估花费防透支要改账本 Lua，留给账本负责人。检查：后端新增 `test/dsh/test_credit_rule_preview.py` 1 条、`test_admin_user_credits.py` 加 5 条，test/llm + test/dsh 失败列表与改动前相同；platform 新增 `CreditRulePreview.test.tsx` 5 条、`dshPolicyView` 2 条、`CreditRulesView` 断言预览，全量 69 条失败与改动前相同；client `components/dsh` + `WorkbenchSidebar` 27 条通过；两端 tsc-strict、eslint、check-i18n、arch-guard 通过；桌面全量 3,865 条 0 失败。本机浏览器核对后台预览（1000 → 剩余 0 并提示透支；1500 → 215.25 / 1,500）、用量页「超出额度 284.75」、网页左下角「0 / 1,000」。桌面开发版未重启目视（Callum 可能在用）。
- 2026-11-13 第二轮自测（计划与结果见 `self-test-2026-11-13.md`）：后端 A 组 4,113 条，platform 相关 622 条，client 相关 261 + 13 条，桌面全量，均无新增失败；浏览器与桌面端到端 13 项全部通过（真实模型，扣费与独立重算一致）。
- 2026-11-13 Callum 对待确认项的决定：①缺价拒绝调用（AC-22）按现方案；②默认汇率改为当前汇率 6.72（`DEFAULT_USD_CNY_RATE_MICRO`，原 7.2），管理员可改、不自动更新。按默认值写的换算测试改为显式使用 7.2（它们验证的是设计文档里的算例），另加一条测试锁定默认值；③桌面倍率标签与 DeepSeek 1017 标签同时显示：倍率不再注册 single 插槽，改为按模型选择包 README 的方式，用名字外层 `data-provider-id` / `data-model-id` 注入样式、以 `::after` 显示（design 决策 12 改为 C）；④租户结构与现设计一致，待确认各子租户积分单价不同导致扣分不同是否可接受；⑤缓存数大于输入的口径已解释，建议保持「加回」，待确认。
- 自测：后端 A 组 4,114 条无新增失败；桌面全量 3,691 条 0 失败、typecheck 通过；桌面开发版实测 Work 下拉框三个模型分别显示 4.17x、1.00x（基准）、Free，旧插槽组件不再出现。本机没有 DeepSeek 官方账号，1017 标签与倍率同屏未实际看到。
- 2026-11-13 晚合入团队最新代码（毕昇 fe4ae2cdd、桌面 b790c4e6）并回归，结果见 `self-test-2026-11-13.md` E 部分：各组与团队最新代码逐条对比，新增失败 0；端到端（改价扣费、选择模型、网页 / 后台 / 桌面积分显示与刷新）全部通过。到 11-16 团队又新增毕昇 15 个、桌面 9 个提交，交代码前还要再同步一次。

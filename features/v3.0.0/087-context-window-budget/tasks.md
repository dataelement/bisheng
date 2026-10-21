# Tasks: 任务模式按模型上下文长度控制上下文

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md) · [plan.md](./plan.md)
**版本**: v3.0.0
**分支**: `feat/3.0.0/087-context-window-budget`（只合入 `feat/3.0.0`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-10-21 用户确认 |
| design.md | ✅ 已评审 | 2026-10-21 用户确认 |
| tasks.md | ✅ 已拆解 | 两轮 `/sdd-review tasks`，第二轮剩余 7 条已修复 |
| 实现 | 🔄 进行中 | 19 / 35 完成（P0 只剩 T018 端到端验证，用户决定到客户现场再验） |

---

## 开发约定

- 后端测试放在 `src/backend/test/llm/` 与 `src/backend/test/linsight/`，`asyncio_mode=auto`。本地跑 pytest 前清掉 SOCKS 代理环境变量。
- 测试任务先于实现任务；每个任务完成后跑 `/task-review`，再勾选。
- 共享工作树规则：不用 `git stash`、`git checkout .`、`git reset --hard` 等仓库级写操作。
- 设计论证一律指向 design.md 的决策编号，本文不复制。

### 接口约定（供跨任务调用）

- `ContextWindowService`（`src/backend/bisheng/llm/domain/services/context_window.py`）：
  - `async def resolve(model: BishengLLM) -> ContextWindowResult`，从不抛异常；读取失败返回 `source="unknown"`。
  - `async def invalidate(model_ids: Iterable[int]) -> None`，Redis 失败只记警告。
  - Redis 客户端用 `bisheng.core.cache.redis_manager.get_redis_client()`。
- `ContextWindowResult` 字段：`window: int | None`、`kind: "total" | "input" | None`、`usable_input: int | None`、`source`。`source` 取值固定为：`manual`（高级配置）、`ollama_num_ctx`、`deployed`（vllm、llamacpp、ollama `/api/ps`、openai 类型读到 `max_model_len`）、`published`（xinference、ollama `/api/show`、anthropic、deepseek、moonshot、openai 类型读到 `context_length`、qwen）、`unknown`。
- 超窗异常：见 design 决策 5。判断一律用 `isinstance(exc, ContextOverflowError)`。

---

## Wave 1 — P0 基础设施与测试（T001 先做，其余可并行）

- [x] **T001**: 错误码与超窗异常类型
  **文件**: `src/backend/bisheng/common/errcode/linsight.py`、`src/backend/bisheng/llm/domain/llm/exceptions.py`（新建）
  **逻辑**: 新增错误码类 `LinsightContextOverflowError`（11075）、`LinsightContextCompressFailedError`（11076）；新增 `LLMContextOverflowError(ContextOverflowError)`，带 `body`、`status_code`、`reported_input_tokens`。错误码已在 release-contract 登记，无需再改。
  **依赖**: 无

- [x] **T002**: 来源优先级与可用输入的测试
  **文件**: `src/backend/test/llm/test_context_window_service.py`
  **逻辑**: 来源优先级（高级配置 > Ollama `max_tokens` > 服务商接口 > 未知）；可用输入三条规则（仅输入上限、Ollama、减最大输出）；`context_window` 非正整数时忽略并继续；高级配置不是合法 JSON 时行为与改动前一致；最大输出 ≥ 上下文长度时按未知处理；每种情况断言 `source` 取值。
  **覆盖 AC**: AC-01, AC-03, AC-08, AC-09
  **依赖**: 无

- [x] **T003**: 缓存与失效的测试
  **文件**: `src/backend/test/llm/test_context_window_cache.py`
  **逻辑**: 假 Redis。命中时不发请求；失败标记 5 分钟内不发请求；`invalidate` 后重新读取；Redis 异常时 `resolve` 按未知返回、不抛出。
  **覆盖 AC**: AC-05, AC-06, AC-07
  **依赖**: 无

- [x] **T004**: 服务商读取器的测试
  **文件**: `src/backend/test/llm/test_context_window_probes.py`，响应体放 `src/backend/test/llm/fixtures/context_window/`
  **逻辑**: `httpx.MockTransport` 回放。每个读取器一个正常用例、一个字段缺失用例，并断言返回的 `source` 与 `kind`。必测：vLLM（多条目按模型名选取；LoRA 条目沿 `parent` 取基础模型）、openai 类型（`max_model_len` 与 `context_length` 两种返回）、llamacpp `/props`、Ollama（`/api/ps` 已加载；未加载回退 `/api/show`）、xinference、anthropic（仅输入上限）、deepseek、moonshot；超时 3 秒视为失败。
  **覆盖 AC**: AC-04, AC-07, AC-09
  **依赖**: 无

- [x] **T005**: 超窗识别与 `context_window` 剥离的测试
  **文件**: `src/backend/test/llm/test_bisheng_llm_context_overflow.py`
  **逻辑**: design 决策 5 表中每条规则用真实报错原文构造 SDK 异常，分别经 `_generate`、`_agenerate`、`_stream`、`_astream` 调用，断言：抛出的异常是 `ContextOverflowError`，同时仍是原 SDK 异常类型，`body`、`status_code` 保留，`__cause__` 为原异常，`reported_input_tokens` 按正则提取；非超窗的 400 原样抛出；四个装饰器在超窗时都不把模型状态写成 ERROR（决策 6）；高级配置含 `context_window` 时客户端构造参数里没有这个键。
  **覆盖 AC**: AC-02, AC-13, AC-15
  **依赖**: T001

- [x] **T006**: 错误分类的测试
  **文件**: `src/backend/test/linsight/test_llm_error_classifier.py`（追加）
  **逻辑**: 超窗异常 → `classify_behavior` 返回 FAIL_FAST，`label_error` 返回 `context_overflow`，`classify_for_event` 的 `error_code` 为 11075；类名为 `LinsightContextCompressFailedError` 的异常 → `context_compress_failed`、11076；包在 `TaskExecutionError` 里时沿 `__cause__` 仍能识别；日常模式 `chat_service` 调用 `label_error` 时得到 `context_overflow`（附带影响，见 design 决策 5）。
  **覆盖 AC**: AC-14
  **依赖**: T001

## Wave 2 — P0 实现

- [x] **T007**: `ContextWindowService` 核心（优先级、可用输入、缓存、失效）
  **文件**: `src/backend/bisheng/llm/domain/services/context_window.py`
  **逻辑**: 按"接口约定"与 design 决策 3、决策 4 实现；读取器以注册表形式接入，本任务只提供注册表与调度，具体读取器在 T008。
  **测试**: T002、T003 通过
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-06, AC-07, AC-08
  **依赖**: T002, T003

- [x] **T008**: P0 七种服务商读取器
  **文件**: `src/backend/bisheng/llm/domain/services/context_window_probes.py`
  **逻辑**: vllm、openai 类型、llamacpp、ollama、xinference、anthropic、deepseek、moonshot；地址和密钥取自 `BishengLLM` 已算好的客户端参数（决策 3）；单次超时 3 秒。
  **测试**: T004 通过
  **覆盖 AC**: AC-04
  **依赖**: T004, T007

- [x] **T009**: `BishengLLM` 超窗识别、剥离 `context_window`、不标异常
  **文件**: `src/backend/bisheng/llm/domain/llm/llm.py`、`src/backend/bisheng/llm/domain/utils.py`
  **逻辑**: `_get_llm_params` 取出 `context_window`；四个调用入口在被装饰函数内部识别超窗并改抛（决策 5，保持原 SDK 类型与属性）；四个装饰器对 `ContextOverflowError` 跳过状态写入（决策 6）。
  **影响范围**: `BishengLLM` 全平台共用。附带影响见 design 决策 5：日常模式的错误分类会得到 `context_overflow`；所有场景超窗不再标模型异常。`test/llm/` 全部既有用例必须不回归。
  **测试**: T005 通过
  **覆盖 AC**: AC-02, AC-13, AC-15
  **依赖**: T001, T005

- [x] **T010**: 错误分类实现
  **文件**: `src/backend/bisheng/common/services/llm_error_classifier.py`
  **逻辑**: 新增两个 `ErrorType`；`label_error` 在最前面识别（压缩失败按类名，避免 common 导入 linsight）；`classify_behavior` 对 `ContextOverflowError` 返回 FAIL_FAST；`classify_for_event` 按类型写入 11075、11076。
  **影响范围**: 共享模块。调用方为 linsight（resilience、失败处理）和日常模式 `chat_service.py:1467`、`:2377`。`:1467` 只判断是否属于临时错误，`context_overflow` 不属于，行为不变；`:2377` 得到新类型，由 T013 的文案覆盖。
  **测试**: T006 通过；`test/linsight/`、`test/workstation/` 中使用分类器的既有用例不回归
  **覆盖 AC**: AC-14
  **依赖**: T001, T006

- [x] **T034**: 保存配置与验证模型时清除缓存的测试
  **文件**: 追加到 `src/backend/test/llm/test_context_window_cache.py`
  **逻辑**: `update_llm_server` 保存后，对每个模型调用了 `ContextWindowService.invalidate`；`verify_model_status` 同样调用；`update_model_online` 不调用。
  **覆盖 AC**: AC-06
  **依赖**: T007

- [x] **T011**: 保存配置与验证模型时清除缓存
  **文件**: `src/backend/bisheng/llm/domain/services/llm.py`
  **逻辑**: 在 `update_llm_server` 里按模型逐个调用 `invalidate_llm_info_cache` 的循环中，调用 `ContextWindowService.invalidate`；`verify_model_status` 中调用 `invalidate_llm_info_cache` 之后同样调用。`update_model_online` 只改上下线状态，不影响上下文长度，不调用。
  **测试**: T034 通过
  **覆盖 AC**: AC-06
  **依赖**: T034

## Wave 3 — P0 接入任务模式

- [x] **T012**: agent_factory 接入的测试
  **文件**: `src/backend/test/linsight/test_agent_factory_context_window.py`
  **逻辑**: 假 `ContextWindowService` 返回可用输入时，主图与研究员子图的压缩中间件处于比例模式，阈值为 `0.85 × 可用输入`；保留比例为 `0.1 × 可用输入`；返回未知时为 170000 tokens、保留 6 条消息；两种情况都有 `[linsight-context-window]` 日志；"继续"、"重试"与"回答提问后恢复"重新构造 agent 时都会再次调用 `resolve`。
  **覆盖 AC**: AC-08, AC-09, AC-11, AC-24
  **依赖**: T007

- [x] **T013**: 前端错误码文案（api_errors）
  **文件**: `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
  **逻辑**: 为 11075、11076 补三种语言文案，措辞对任务模式与日常模式都成立（design 决策 8）。改完运行 `pnpm locales:build` 重新生成 `client/src/locales/*/api_errors.gen.json` 与 `platform/public/locales/*/api_errors.json`，生成产物不手改。
  **手动验证**: `pnpm --filter @bisheng/locales check`、`pnpm check-i18n` 通过。
  **覆盖 AC**: AC-14, AC-18
  **依赖**: T001

- [x] **T014**: agent_factory 接入实现
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: `_resolve_model` 之后、`create_deep_agent` 之前调用 `ContextWindowService.resolve`；可用输入非空时设置 `model.profile`（决策 1、决策 2）；记录 `[linsight-context-window]` 日志。
  **测试**: T012 通过
  **覆盖 AC**: AC-08, AC-09, AC-11, AC-24
  **依赖**: T008, T012

- [x] **T015**: 超窗压缩重试与子任务降级的测试
  **文件**: `src/backend/test/linsight/test_context_overflow_flow.py`
  **逻辑**: 假模型按序列返回。主图：第一次超窗 → 压缩 → 第二次成功；两次都超窗 → `output_result.error_type == "context_overflow"`、`error_code == 11075`，日志含 `reported_input_tokens`，已生成文件保留；同一次请求最多压缩一次。中文场景：构造"估算未到阈值、实际超窗"的序列，断言走超窗后压缩重试（design 决策 1 的 P0 局限）。子图：两次都超窗 → 主图收到超窗说明（工具结果为成功状态）并继续；累计超过 `max_degrade` → 任务以 `context_overflow` 失败。resilience 对超窗直接抛出（主图与子图）。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-16
  **依赖**: T009, T010, T014

- [x] **T016**: resilience 与 `task` 超窗中间件实现
  **文件**: `src/backend/bisheng/linsight/domain/services/resilience_middleware.py`、`src/backend/bisheng/linsight/domain/services/agent_factory.py`、`src/backend/bisheng/linsight/domain/task_exec.py`（`_handle_task_failure`）
  **逻辑**: resilience 对超窗直接抛出；新增主图 `wrap_tool_call` 中间件，只处理 `task` 工具的超窗异常，与研究员 resilience 实例共用降级计数（决策 9）；主图失败时在 `_handle_task_failure` 记录 `reported_input_tokens`，子图超窗时由新中间件记录（AC-15）。
  **测试**: T015 通过；`test_resilience_middleware.py` 不回归
  **覆盖 AC**: AC-13, AC-15, AC-16
  **依赖**: T015

- [x] **T017**: 失败卡片的新类型与文案
  **文件**: `src/frontend/client/src/components/ChatErrorCard.tsx`、`src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 两个新类型加入 `KNOWN_TYPES`（不进 `TRANSIENT_TYPES`），三种语言各补 title、desc、hint 三个键，措辞对任务模式与日常模式都成立（决策 8）。只加文案，不改卡片样式。如果改动的文件里有冻结的硬编码中文，按根 AGENTS.md 规则在同一改动中提取。
  **手动验证**:
  - 在 114 上构造一个超窗失败的任务，打开 `/workspace` 任务页，确认卡片显示新文案；切换三种语言各看一次。
  - 在日常模式触发一次超窗，确认文案读起来也成立。
  - `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n` 通过；改完运行 `pnpm lint:prune`。
  **覆盖 AC**: AC-14
  **依赖**: T010, T013

- [x] **T035**: 刷新后恢复失败类型
  **文件**: `src/frontend/client/src/hooks/linsightErrorInfo.ts`（新建，严格类型）、`src/frontend/client/src/hooks/useLinsightManager.tsx`
  **逻辑**: 从 `output_result.error_type`、`error_code`、`detail` 恢复 `taskErrorInfo`（决策 8）。`useLinsightManager.tsx` 已有 635 行、带 `@ts-strict-ignore`：恢复逻辑写在新文件里，原文件两处恢复点（现 `:134`、`:203`）各改为调用新函数，净增行数不超过 2 行。
  **手动验证**:
  - 构造一个超窗失败的任务后刷新页面，确认文案不变，不退回"未知错误"。
  - 从历史列表重新打开该任务，确认同上。
  - `pnpm lint`、`pnpm typecheck` 通过；改完运行 `pnpm lint:prune`。
  **覆盖 AC**: AC-14
  **依赖**: T017

- [ ] **T018**: P0 端到端验证
  **文件**: 无代码；结果记在"实际偏差记录"或 PR
  **逻辑**: 跑 `/e2e-test`；按 design §7 的手动验证步骤，在 `--max-model-len 32768` 的 vLLM 上执行中文长文档任务，再用 133120 复验客户场景。
  **测试降级**: AC-12 需要真实 vLLM 部署和 GPU，无法在 CI 自动化；自动化部分由 T015 的假模型序列覆盖。
  **覆盖 AC**: AC-04, AC-09, AC-11, AC-12
  **依赖**: T011, T014, T016, T017, T035

## Wave 4 — P1

- [ ] **T019**: 技术验证：替换框架压缩中间件
  **文件**: 验证脚本放 scratchpad；结论写入 design.md 决策 7
  **逻辑**: 回答决策 7 的两个问题；确认 BiSheng 子类改 `name` 后不被排除规则移除；确认主图、子图都能拿到当次参数。不通过时停下与用户重新确认路线。
  **依赖**: T018

- [ ] **T020**: 中日韩计数与用量基数的测试
  **文件**: `src/backend/test/linsight/test_context_token_counter.py`
  **逻辑**: 纯中文、中英混合；有 usage 基数时只估算增量；无 usage 时全量估算；最近一条是降级合成消息（无 usage）时向前找。
  **覆盖 AC**: AC-21
  **依赖**: 无

- [ ] **T021**: 中日韩计数与用量基数的实现
  **文件**: `src/backend/bisheng/linsight/domain/services/context_budget.py`
  **逻辑**: 按 design 决策 10 实现纯函数。
  **测试**: T020 通过
  **覆盖 AC**: AC-21
  **依赖**: T020

- [ ] **T022**: BiSheng 压缩中间件子类的测试
  **文件**: `src/backend/test/linsight/test_context_summarization.py`
  **逻辑**: 摘要输入不超过 `0.5 × 可用输入`；保留部分不超过 `0.1 × 可用输入`；摘要第一次失败、重试成功；两次都失败 → 抛 `LinsightContextCompressFailedError`，任务 `error_type == "context_compress_failed"`、`error_code == 11076`，日志有错误级别记录，已生成文件保留，失败文本没有作为摘要进入下一次请求；计数使用 T021 的函数。
  **覆盖 AC**: AC-17, AC-18, AC-21, AC-24
  **依赖**: T019, T021

- [ ] **T023**: BiSheng 压缩中间件子类的实现
  **文件**: `src/backend/bisheng/linsight/domain/services/context_budget.py`、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 按 T019 的结论接入，主图与研究员子图都使用。
  **测试**: T022 通过
  **覆盖 AC**: AC-17, AC-18, AC-21, AC-24
  **依赖**: T022

- [ ] **T024**: 单条工具结果转存与读文件截断的测试
  **文件**: `src/backend/test/linsight/test_tool_result_budget.py`
  **逻辑**: 已知上下文长度时，超过 `0.1 × 可用输入` 的工具结果写入 `/large_tool_results/<tool_call_id>`，返回开头片段与路径；`read_file` 结果截断到同一上限并提示分页，不转存；主图与子图都生效；未知上下文长度时行为与改动前一致。
  **覆盖 AC**: AC-19, AC-20
  **依赖**: T021

- [ ] **T025**: 单条工具结果转存与读文件截断的实现
  **文件**: `src/backend/bisheng/linsight/domain/services/context_budget.py`、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 新增 `wrap_tool_call` 中间件；提示文案与 `tool_loop_middleware` 现有的取回提示一致。与 T023 改同一组文件，串行执行。
  **测试**: T024 通过
  **覆盖 AC**: AC-19, AC-20, AC-24
  **依赖**: T023, T024

- [ ] **T026**: 百炼读取器的测试
  **文件**: 追加到 `src/backend/test/llm/test_context_window_probes.py`
  **逻辑**: 从兼容模式地址推导原生地址；北京区域缺 WorkspaceId 时按未知处理；`source == "published"`。
  **覆盖 AC**: AC-10
  **依赖**: T008

- [ ] **T027**: 百炼读取器的实现
  **文件**: `src/backend/bisheng/llm/domain/services/context_window_probes.py`
  **测试**: T026 通过
  **覆盖 AC**: AC-10
  **依赖**: T026

- [ ] **T028**: P1 端到端验证
  **文件**: 无代码
  **逻辑**: 跑 `/e2e-test`；重复 T018 的中文长文档任务，确认压缩改为提前触发（日志中不再出现被识别的超窗），每次请求的服务商用量不超过可用输入；人为让摘要调用失败一次，确认重试；检查大工具结果被转存。
  **测试降级**: AC-21 以服务商实测用量为准，需要真实部署。
  **覆盖 AC**: AC-17, AC-19, AC-21, AC-24
  **依赖**: T023, T025, T027

## Wave 5 — P2

- [ ] **T029**: 死配置清理的测试
  **文件**: `src/backend/test/common/test_linsight_conf_legacy_keys.py`
  **逻辑**: 含 AC-22 所列 6 个键的 `linsight` 配置能被 `LinsightConf` 正常加载；删除后这些属性不再存在。
  **覆盖 AC**: AC-22, AC-23
  **依赖**: 无

- [ ] **T030**: 删除死配置
  **文件**: `src/backend/bisheng/core/config/settings.py`（`LinsightConf`）、`src/backend/bisheng/initdb_config.yaml`、`src/backend/bisheng_langchain/linsight/const.py`
  **逻辑**: 从 `LinsightConf` 和 `initdb_config.yaml` 删除 6 个字段。`const.py` 的 `ExecConfig` 类没有任何引用（已 grep 确认），整个类删除；同文件的 `TaskStatus` 等仍在使用，保留。`test/common/test_config_backfill.py` 使用自带的内联配置，不受影响。
  **测试**: T029 通过
  **覆盖 AC**: AC-22, AC-23
  **依赖**: T029

## 收尾

- [ ] **T031**: P0 代码审查与合并
  **逻辑**: `/code-review --base feat/3.0.0`，合并 P0。
  **依赖**: T018

- [ ] **T032**: P1、P2 代码审查与合并
  **逻辑**: `/code-review --base feat/3.0.0`；P1、P2 在同一分支继续或另开 PR，以用户决定为准。
  **依赖**: T028, T030

- [ ] **T033**: 收尾清理
  **逻辑**: 合并后按用户的 worktree 清理规则删除 `bisheng-087-context-window` worktree 与本地分支。
  **依赖**: T032

---

## AC 覆盖检查

| AC | 测试任务 | 实现任务 |
|---|---|---|
| AC-01 | T002 | T007 |
| AC-02 | T005 | T009 |
| AC-03 | T002 | T007 |
| AC-04 | T004, T018 | T008 |
| AC-05 | T003 | T007 |
| AC-06 | T003, T034 | T007, T011 |
| AC-07 | T003, T004 | T007 |
| AC-08 | T002, T012 | T007, T014 |
| AC-09 | T002, T004, T012, T018 | T014 |
| AC-10 | T026 | T027 |
| AC-11 | T012, T018 | T014 |
| AC-12 | T018（测试降级） | — |
| AC-13 | T005, T015 | T009, T016 |
| AC-14 | T006, T015 | T010, T013, T017, T035 |
| AC-15 | T005, T015 | T009, T016 |
| AC-16 | T015 | T016 |
| AC-17 | T022, T028 | T023 |
| AC-18 | T022 | T013, T023 |
| AC-19 | T024, T028 | T025 |
| AC-20 | T024 | T025 |
| AC-21 | T020, T022, T028 | T021, T023 |
| AC-22 | T029 | T030 |
| AC-23 | T029 | T030 |
| AC-24 | T012, T022, T028 | T014, T023, T025 |

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已确认的决策时，先停下与用户重新确认。

- T004 偏离：响应体直接写在测试文件里，没有单独放 `fixtures/context_window/`（每个只有几行，内联更易读）。
- T034 偏离：实现（T011）先于测试写成；测试为源码级断言（驱动 `update_llm_server` 需要数据库）。
- T035 偏离：`useLinsightManager.tsx` 净增 3 行（2 处调用 + 1 行导入），不是"不超过 2 行"。
- T010 偏离：`unwrap` 增加"遇到超窗 / 压缩失败异常即停止"，原 design 未写 → 已补 design §5 坑 17。
- T015：发现框架主动压缩后不再接住超窗 → design §5 坑 15、16。
- T018 推迟：2026-10-21 用户决定在客户现场（vLLM 133120）做端到端验证，界面三项手动检查一并在现场做。
- T017 / T035 验证：改动的 3 个文件 eslint、tsc 无错误；`pnpm lint` / `pnpm typecheck` 整体报错都在其他文件（worktree 软链了 vibe 分支的 node_modules，未与 feat/3.0.0 干净环境对比）；`check-i18n`、`locales check` 通过。手动界面验证未做。

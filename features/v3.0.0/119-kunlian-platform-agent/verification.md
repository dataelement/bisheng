# F119 实施验证记录

- **Status**: IN_PROGRESS / NOT_VERIFIED
- **Updated**: 2026-11-05（Asia/Shanghai）
- **范围** — 用户授权 T001—T040 的 Mock 实施。T001—T038 完成本地实施，38 / 40；T039、T040 的脚本和示例已交付，正常环境验收待执行，不勾选。T041—T050 继续待执行。
- **代码状态** — 基线 HEAD 为 `b870baa3f`，实际源文件 SHA-256 见 [source-state.json](./source-state.json)。当前为未提交的工作树变更，没有部署、推送或真实数据迁移。

## 当前结论

默认 Mock 已接通；本次修复用户信息字段不匹配导致目录根本不发请求的问题。当前前端 **11 passed**、后端定向 **34 passed**，工作区直接执行的 lint／typecheck、三语及 Ruff 通过，Vite 已返回修复后的源码模块。上一批完整相关回归为 E-019 的 **153 passed、1 skipped**，保留为历史证据。正常 API／Broker／Worker E2E、真实登录浏览器及昆联环境仍未验收，不能宣称 Mock 阶段验收通过。

## 环境

E-001—E-017 验证时，工作区 src/backend/.venv 为 Python 3.10.19，复用相邻已存在的 Python 3.11.14 环境，解释器为 /Users/wenruli/code/project/bisheng/bisheng-kunlian-sso-planning/src/backend/.venv/bin/python，PYTHONPATH 显式指向当前仓库 src/backend。本次 E-018 检查时工作区 .venv 已为 Python 3.14.0；相关回归仍使用既有 Python 3.11，另外在当前 3.14 环境复验真实 API 导入。未修改任一虚拟环境或依赖锁。

测试配置使用 /tmp/bisheng-f119.t6hMHt/config.yaml，仅含空 YAML 对象，没有真实服务凭据。表读写仅发生在进程内 SQLite。

当前工作区前端 node_modules 较旧，缺少已声明的 react-query v4 和共享包。验证时将当前前端源码复制到 `/tmp/bisheng-f119.t6hMHt/frontend`，仅在该目录复用相邻工作区的既有依赖，工作区依赖声明和锁文件未修改。最终逐文件比较本批前端文件，副本与当前工作区无差异。使用 Node 24.14.0、pnpm 9.15.9；早期默认 Node 20.13.1 产生 engine 警告，最终门禁已改用符合项目要求的 Node 24。没有在原工作区安装依赖或启用服务。

## 第一批基础契约

| Evidence | 命令或步骤 | 结果与边界 |
| --- | --- | --- |
| E-001 | Python 3.11 内联断言，检查 WorkflowConf 默认关闭、非法模式拒绝、模型自动发现、MySQL CreateTable 编译、隔离 SQLite 提交读取及 12 个错误类的秘密探针。 | PASS，exit 0。只证明模型声明、基本读写及安全错误合同，不能替代真实 DB 行锁。 |
| E-002 | 当前工作区 ruff check，覆盖新模型、规范化类型、Workflow 设置和错误文件。 | PASS，exit 0。初次中文文档字符串全角逗号触发 RUF002，已改为句号并复验。 |
| E-003 | node src/frontend/packages/locales/scripts/build.mjs --check；node src/frontend/scripts/check-i18n.mjs。 | PASS，exit 0。先通过既有 build 生成两端 api_errors，三语无新增漂移。 |

本批 L1 自审覆盖 T001—T007。新增 SQLModel 由 Workflow 所有，JsonType 和租户模型登记存在，设置未反向导入领域模块，错误码 10551—10562 实施前扫描无占用。错误类忽略外部传入的原始异常及消息，避免 BaseErrorCode 默认错误序列化输出秘密。源文案和机械生成件分别维护。

## 第二批资源、Schema 与仓储

| Evidence | 命令或步骤 | 结果与边界 |
| --- | --- | --- |
| E-004 | 同一 Python 3.11 运行 `pytest test/workflow/test_platform_agent_contract.py test/workflow/test_platform_agent_repository.py test/workflow/test_platform_agent_api.py -q --disable-warnings --tb=short`。 | PASS，19 passed，exit 0。先观察仓储和路由模块缺失的收集失败，再实现。初次分页断言误把 B 的两项资源当成三项，修正为按实际授权目录验证。 |
| E-005 | Ruff check 新 domain／api／application 及两项测试；arch-guard 检查领域服务。 | PASS，exit 0。SQL 均封装在 Repository；跨租户和本地编辑权限先于 Provider。 |

T008—T017 的 L1 自审：SQL 使用 JsonType 模型和短事务，发布按 Flow→FlowVersion 加锁；SQL 与上游异常不公开原文；目录、详情、validate 复用 F048，无身份覆盖字段。隔离 SQLite 覆盖冻结图、重复领取、重复发送、停止和输出事务回滚；不能证明 MySQL／DM8 行锁并发。接口测试使用 ASGI 与受控授权桩，不计为真实 OpenFGA 或 Broker E2E。

## 第三批节点、发布及运行接线

| Evidence | 实际执行 | 结果与边界 |
| --- | --- | --- |
| E-006 | 先执行 `test_platform_agent_node.py`，观察节点模块缺失；先执行 bridge 测试，观察 run_once 缺执行上下文、发布仍调用旧 DAO 的失败；先执行 entrypoints 测试，观察队列作用域入口缺失。 | 测试先行证据。对应实现后转绿。 |
| E-007 | 定向节点、版本桥接及队列测试；随后纳入旧试运行、Agent、Code、Workflow 状态和 F118 Worker／WS 回归。最终命令见下。 | **98 passed、1 skipped，exit 0**。包含 SQLite 快照／发布冲突、版本保存切换删除、实际 B、目录撤权、总预算、重复派发、恢复换 owner、迟到输出及 SQL 提交失败回滚。|
| E-008 | `mock-workflow.example.json` 由真实 GraphEngine／Workflow 在进程内运行，外部依赖桩、用户事实和 F048 判定受控。 | PASS：输出 `F119 Mock / B`，下游对象中的 false 保持布尔类型。仅为本地图执行验证，不是正常 API／Broker E2E。 |

最终后端命令（cwd 为 `src/backend`；解释器及空配置见环境）：

```bash
env PYTHONPATH=$PWD config=/tmp/bisheng-f119.t6hMHt/config.yaml \
  /Users/wenruli/code/project/bisheng/bisheng-kunlian-sso-planning/src/backend/.venv/bin/python -m pytest \
  test/workflow/test_platform_agent_contract.py \
  test/workflow/test_platform_agent_repository.py \
  test/workflow/test_platform_agent_api.py \
  test/workflow/test_platform_agent_node.py \
  test/workflow/test_platform_agent_workflow_bridge.py \
  test/workflow/test_platform_agent_entrypoints.py \
  test/workflow/test_platform_agent_e2e.py \
  test/workflow/test_run_once_off_event_loop.py \
  test/workflow/test_workflow_tasks.py \
  test/workflow/test_workflow_offline_input.py \
  test/workflow/test_agent_node_history.py \
  test/workflow/test_code_node_switch.py \
  test/workflow/test_workflow_auto_rerun_status.py \
  test/sso/test_kunlian_worker.py \
  test/sso/test_kunlian_ws_admission.py \
  -q -rs --disable-warnings --tb=short --show-capture=no
```

测试中用户 Owner、F048、队列和 MinIO 按独立边界受控，SQL 仓储为隔离 SQLite。`test_open_entry...`、`test_browser_entry...` 验证实际入口保存快照后投递引用、正式 WS 不接受请求中的 V2 替换、队列异常记录 ABORTED；它们不是实际 Celery 执行。F118 WS 回归因新增服务端发布图读取缺少夹具而初次失败，增加普通空图读取桩后转绿；身份和因果头的原断言保留。

## 第四批 Platform 及静态门禁

| Evidence | 实际执行 | 结果 |
| --- | --- | --- |
| E-009 | Node 24 下，在验证副本的 platform 执行 `node node_modules/vitest/vitest.mjs run src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx`。 | **3 passed，exit 0**。覆盖草稿固定版本、0／false、资源 ID 过滤、版本更换、身份与租户缓存隔离、查询失败与空态。共享选择器使用可操作测试桩，浏览器视觉未验证。故障样例的 `fixture outage` stderr 为预期的 react-query 日志。 |
| E-010 | Node 24 下，在验证副本根目录执行 `pnpm lint`、`pnpm typecheck`。 | **均 exit 0**。覆盖 Platform、Client 及根脚本指定共享包；严格检查分别识别 Platform 1039、Client 1727 文件。只有既有工具的 DEP0169 提示。 |
| E-011 | `node src/frontend/packages/locales/scripts/build.mjs --check`；`node src/frontend/scripts/check-i18n.mjs`。 | **PASS，exit 0**。无新增三语漂移，84 个原有 frontend-only 错误键为提示信息。 |
| E-012 | 本批后端文件 Ruff check／format、`git diff --check`；源文件 SHA-256 记录及前端副本字节比较。 | **PASS，exit 0**。Ruff 顺带修正被修改文件既有 Optional 注解和中文文档字符串标点，没有业务扩展。 |

前端最终命令通过 `env PATH=/Users/wenruli/.nvm/versions/node/v24.14.0/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` 固定 Node，再调用该目录的 pnpm／node。副本只用于本地验证，没有生成生产发布或部署产物。使用既有 lint prune 命令缩减 Sidebar 的历史抑制项，未手写或增加豁免。

## L1 与阶段审查

- T001—T038 的范围、依赖、测试先行和本地证据已复核。模型归 Workflow、SQL 在 Repository、身份事实走用户应用端口、业务动作走 F048；不保存 Token 或业务结果到执行事实表。
- 复核后补齐：echo V2 的不兼容输入／输出样例及下游引用校验；开放入口拒绝服务账号所有者代替实际用户；当前 token_version；固定图和 START／RESUME 区分；旧启动／停止／回调隔离；SQL 提交失败恢复内存；非终态和停止保留远端结果未知；Agent 返回运行标识及失败日志安全字段。
- 当前修改文件逐个执行 arch-guard。`common/chat/clients/workflow_client.py` 报两条 RULE-1，`core/config/settings.py` 报一条 RULE-7。已将 `git show HEAD:<path>` 的原文件置于相同目录结构运行守卫，输出逐字一致；这是原有兼容层耦合和原有设置字面量，不能将其记为“守卫全量通过”。本次未新增守卫报告，也未扩大为公共层迁移或凭据配置改造。
- 七维阶段检查见 [code-review.md](./code-review.md)。这是当前未提交 Mock 工作树的阶段审查，完整 Feature 的合入审查和 M-MOCK 阶段验收未关闭。

## T039／T040 待执行

T039 脚本已执行到前置检查，得到 **1 skipped / NOT_RUN**，不能计作正常 API E2E 通过。本机 127.0.0.1:7860、6379、3306 的只读连接检查均为 unavailable。未启动服务、未部署，也未使用共享或生产环境账号。

T040 的示例、本文及源码状态文件已交付；示例在本地图引擎通过。由于依赖 T039 的正常环境结果，任务保持 PARTIAL。专用账号、配置、执行命令和手动步骤见 [e2e-checklist.md](./e2e-checklist.md)。浏览器交互及真实中间件仍待执行。

### TODO 对应关系

| EXT | 实际位置 | 当前内容 |
| --- | --- | --- |
| EXT-01 | `domain/clients/platform_agent.py`、`platform_agent_mock.py` | 目录、版本、Schema 为模拟；echo V2 有意与 V1 不兼容。 |
| EXT-02 | 同上 | 当前外部身份为 A／B／C 映射；本地账号、租户和 F048 校验仍执行。真实 Token／委托等待昆联合同。 |
| EXT-03 | 同上 | 成功、错误、超时、错误输出和非终态为 Mock；真实工厂明确未就绪，不回落 Mock。 |

TODO 仍以 `# TODO [F119][EXT-NN]` 保留在具体来源和占位位置。T041—T047 没有实施；真实环境任务不因本次 Mock 通过而改变状态。

## 2026-11-05 代码审查与修复

以下为本轮新证据。E-001—E-012 保留为历史实施证据，不将旧结果冒充修复后的结果。HEAD 仍为 `b870baa3f`；source-state.json 记录当前 63 个源码文件，以及本轮修改的 13 个既有文件和新增纳入的 3 个接线文件。未暂存、提交、推送、部署或执行真实迁移。

| Evidence | 实际命令／步骤 | 结果与边界 |
| --- | --- | --- |
| E-013 | 在 entrypoints 测试增加受理后 Schema 漂移和 Worker 失败参数组，先运行 `pytest test/workflow/test_platform_agent_entrypoints.py -k 'debug_admission_binds or worker_failure_finishes' -q --disable-warnings --tb=short --show-capture=no`；组件增加更换版本后清理旧映射，并将常量断言提前到失焦前。 | 后端 **5 failed**，分别为漂移未拒绝、两类拒绝停在 READY、构造和恢复停在 RUNNING；前端 **2 failed、2 passed**。另补测得到结束时配置变化 **1 failed**，本地登录版本提示 **2 failed，exit 1**。都在修复后转绿。 |
| E-014 | Python 3.11、空配置及 PYTHONPATH 同环境节。执行上文 E-007 的同一后端命令，在测试路径后追加 `test/public_endpoints/test_public_websocket_denial.py test/public_endpoints/test_chat_compatibility.py`，其他参数不变。 | **135 passed、1 skipped、8 warnings，exit 0，13.13s**。覆盖临时绑定、实际身份、19103 重登原因、拒绝后的所属执行终态、旧 owner 隔离、安全日志／WS、路由与连接端口传递、正式图、普通流程及既有 Workflow／F118／公开入口回归。恢复输入补测先得到 **1 failed、2 passed**：Redis 交接失败仍抛原始异常；统一安全错误后，正常恢复、失效前拒绝写入及失败中止均通过。 |
| E-015 | Node 24 下在同一验证副本运行 PlatformAgentItem 的 Vitest、根目录 `pnpm lint` 和 `pnpm typecheck`；测试样例补齐后定向 `pnpm exec eslint` 两个组件文件。继续执行三语构建检查和 check-i18n。 | **组件 4 passed；lint、typecheck、定向 ESLint、三语检查均 exit 0**。类型检查初次发现两处测试样例缺少 provider_mode／policy_revision，补齐后通过，未增加豁免。23 个前端实现文件逐字节与工作区相同。 |
| E-016 | 11 个本轮后端文件 `ruff format --check`、`ruff check`；本轮修改文件逐个 arch-guard，并比较新增触及兼容文件与 HEAD 的报告。AST 检查 common 的顶层及嵌套导入。 | **Ruff exit 0**。common 不再直接导入任何 F119 领域或应用模块。workflow_client／manager 各两条历史 RULE-1、旧 workflow 路由一条 RULE-3 与 HEAD 输出相同；settings 的历史 RULE-7 复用 E-012，未修改该文件。不能据守卫数量一致认定语义合规，本轮已单独修正新增领域依赖。全库历史架构欠账不计通过。 |
| E-017 | `git diff --check`、文档本地引用检查、source-state.json 的 SHA-256 与验证副本比较、暂存区摘要比较；只读检查本机 7860／6379／3306 端口。 | 文档／源码状态检查通过；暂存区仍为原先 5 个文件且内容未变。本轮端口检查均 unavailable，不启动环境。T039 脚本仍 **NOT_RUN / 1 skipped**，不把跳过计为通过。 |

复验范围为 17 个相关测试文件；SQL 仍为隔离 SQLite，用户 Owner／F048／队列和对象存储依赖仍受控。额外 24 个公开入口回归用于验证连接装配及原有行为，不能替代真实用户、真实 OpenFGA 或真实队列。Node 的 fixture outage stderr 是有意的失败样例，DEP0169 和后端依赖告警保留。

本轮将浏览器新增领域职责收回 `BrowserPlatformAgentRuntime`，仅通过既有连接构造参数传递。普通图不创建 Provider；没有新 HTTP／WS 接口、真实凭据来源、数据库列、权限策略或新增依赖。DEBUG 生成临时绑定，单节点试运行仅允许显式传入的变量作为上游值，不能借此跳过常量、必需字段或输出验证。真实委托、Access Token 有效性及外部 API 仍在 T041—T047，不能由本地 token_version 用例代替。

T001—T038 继续保留本地完成；本轮 R1—R5 修复已验证。T039、T040 继续 PARTIAL，T041—T047 为 WAITING_EXTERNAL，T048—T050 为 NOT_RUN。浏览器手动清单保持待执行。

## E-018：修复 API 首次导入循环依赖

用户日志中的致命错误为 `WorkFlowService` 循环导入。链路为 `main → API router → WorkFlowService → Workflow／NodeFactory → PlatformAgentNode → worker._asyncio_utils → worker/__init__ 的任务注册 → telemetry.mid_table → 未初始化的 WorkFlowService`。Python 3.14 的 Pydantic V1、jieba 等警告与该错误分开处理；同一循环在 Python 3.11 也已复现。

仅将平台节点的桥接改为已有 `bisheng.utils.async_utils.run_async_safe`。显式传入 timeout=None，避免通用桥接的默认 10 秒覆盖领域总预算；API 线程复用请求循环，Celery 复用原先登记的循环。没有改动通用桥接、Worker 注册、依赖声明、当前 .venv 或运行配置。

原回归运行在 `test/conftest.py → premock_import_chain()` 已处理部分 Worker 模块的进程内，不能证明实际 API 首次导入可用。新增 `test/workflow/test_platform_agent_imports.py`，参数化真实服务及 `bisheng.main`，每项使用全新子进程、空配置和当前源码路径；不装模块桩、不使用最小应用兜底，校验真实 run_once 路由，并拦截网络连接。仅导入，不执行 lifespan、监听端口或部署。

| 步骤 | 命令／范围 | 结果 |
| --- | --- | --- |
| 失败复现 | Python 3.11，`pytest test/workflow/test_platform_agent_imports.py -q --disable-warnings --tb=short --show-capture=no`。 | **2 failed，exit 1**；均复现用户日志中的同一 WorkFlowService 循环导入。 |
| 定向复验 | 上述导入测试，加 `test_platform_agent_node.py`、`test_platform_agent_workflow_bridge.py` 和 `test/common/test_async_utils.py`。 | **26 passed，exit 0**，12.03s。涵盖节点成功／失败、超时、试运行、既有桥接循环复用和上下文。 |
| 相关回归 | Python 3.11，执行 E-014 的 17 文件命令，再加 `test/workflow/test_platform_agent_imports.py test/common/test_async_utils.py`，其余参数相同。 | **148 passed、1 skipped、8 warnings，exit 0**，24.23s。唯一跳过仍为 T039 正常 API／Broker／Worker E2E。 |
| 用户当前环境 | cwd=src/backend，`env PYTHONPATH=$PWD config=/tmp/bisheng-f119.t6hMHt/config.yaml .venv/bin/python -m pytest test/workflow/test_platform_agent_imports.py -q --disable-warnings --tb=short --show-capture=no`。 | **Python 3.14.0：2 passed、17 warnings，exit 0**，12.48s。只证明真实 API 导入通过，不能据此宣称 3.14 全栈兼容或服务已启动。 |
| 静态与状态 | 节点及新增测试的 Ruff check／format、arch-guard、diff 检查；源码 SHA-256、文档引用及本次开始时的暂存区摘要比较。 | Ruff 和定向守卫通过；当前 64 个源码文件纳入状态记录。原有 37 项暂存内容保持不变，未暂存、提交或修改用户配置。 |

项目 backend/AGENTS.md 仍要求 Python 3.11.x。现有 3.14 环境的依赖警告保留，未尝试升级／降级或重建环境。T039、T040、T048—T050 的环境验收继续待执行。

## E-019：默认启用 Mock，无需手工主体配置

用户明确要求“不需要配置默认启动就好”，授权覆盖原先默认 disabled 的设计。spec 的 AC-23、design、T003／R7、版本登记及联验清单已同步。仅改变默认值和空 Mock 映射行为，不改实际后台配置、身份或 Workflow 权限：

- 未配置 platform_agent 或省略 mode 时，`PlatformAgentConf` 默认 mock。
- 空 mock_subjects 使用通用 B 样例，提供 echo 与故障场景，不开放 A 专用 private 样例。实际用户／租户仍由可信上下文取得，并经过用户 Owner 与 F048 校验。
- 非空专项映射继续严格匹配，未映射用户拒绝；显式 disabled／real 保持关闭／未就绪，不回落 Mock。读取配置异常时，能力接口仍关闭。
- 运行中的旧 API／Workflow Worker 需重启加载新默认值，然后刷新画布。此次未重启、未部署，也未修改数据库配置或安装依赖。

| 步骤 | 实际执行 | 结果 |
| --- | --- | --- |
| 测试先行 | `pytest test/workflow/test_platform_agent_contract.py -k 'default_configuration or explicit_mock_subject_map' ...`；再单独执行显式 mode=mock、空映射场景。 | 前者 **3 failed、1 passed，exit 1**，默认仍 disabled；后者 **1 failed，exit 1**，空映射仍拒绝。均在修改后转绿。 |
| 定向验证 | `pytest test/workflow/test_platform_agent_contract.py test/workflow/test_platform_agent_node.py test/workflow/test_platform_agent_api.py -q --disable-warnings --tb=short --show-capture=no`。解释器、PYTHONPATH 与空配置同 E-018。 | **34 passed，exit 0**。默认目录／调用、非空映射拒绝、显式关闭和 real、类型及权限回归通过；真实 GraphEngine 示例已改用无参数 PlatformAgentConf 并输出 `F119 Mock / B`。 |
| 能力接口 | 新进程使用空 YAML；拦截网络连接，只将 ConfigService.get_all_config 替换为空配置来源，执行真实 get_env。 | **exit 0**：platform_agent_enabled=true、platform_agent_mode=mock、policy_revision=mock-v1。未连接或写入真实服务，不代表当前旧进程已热更新。 |
| 相关回归 | 与 E-018 的 19 文件、同一 Python 3.11 命令及参数。 | **153 passed、1 skipped、8 warnings，exit 0**，24.64s。唯一跳过仍为 T039 正常环境 E2E。 |
| 当前解释器导入 | Python 3.14，复用 E-018 的 `test_platform_agent_imports.py` 命令。 | **2 passed、17 warnings，exit 0**，12.88s。新默认值下真实服务及 main 均能独立导入；依赖兼容警告仍保留。 |
| 静态／范围 | 四个修改的后端实现／测试执行 Ruff check、format --check、逐文件 arch-guard；源码 SHA-256、文档引用和本次开始时的暂存区摘要检查。 | Ruff 通过；settings 原有一条 RULE-7 与 HEAD 相同，其余三文件无报告。源码清单仍 64 项，本次仅 4 项内容变化。原有 37 项暂存内容不变。 |

E-001 中“默认关闭”是历史初版证据，其默认行为结论由本条取代；其余历史测试结果不改写。前端代码未变化，原组件与门禁证据复用。T039、T040 及真实环境任务状态不变。

## E-020：修复 Mock 目录空白与补齐样例名称

用户截图中节点可见，但能力标签和选项都未显示。只读查询本地 `/api/v1/env` 及前端代理，确认 mode=mock、enabled=true、multi_tenant_enabled=false。追溯发现：`/user/info` 的 tenant_id 为可选，叶租户通过 leaf_tenant_id 提供；前端却要求 tenant_id 非空才发能力和目录请求。后台已有 Mock 数据，空白不能据此判断为无数据。

修复仅涉及前端请求前提、缓存作用域、提示及 Mock 目录名称：先按已登录用户请求能力；租户取 tenant_id／leaf_tenant_id；服务器明确关闭多租户时允许缺少租户字段，多租户信息缺失则提示并阻断。目录、版本及使用授权继续由后端判断，前端不填造选项、不透传身份或伪造租户。能力适配器完整保留服务器 true／false／缺失的多租户标志。

| 步骤 | 实际执行 | 结果与边界 |
| --- | --- | --- |
| 失败复现 | 在真实工作区执行 PlatformAgentItem Vitest，增加叶租户、单租户无字段和多租户缺失身份三项场景。 | **3 failed、4 passed，exit 1**；叶租户／单租户均未出现已有选项，多租户缺失身份也没有提示。 |
| 前端复验 | cwd=src/frontend/platform，`pnpm exec vitest run src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx src/controllers/API/workflow.test.ts`。最终固定 Node 24.14.0 的 PATH。 | **11 passed，exit 0**：组件 8、API 适配 3。包含选择 Agent／版本、两种字段下同一用户换租户后的缓存隔离、身份未就绪阻断、空态／错误及原配置回归。共享 Select 使用测试桩，不能代替浏览器验收。 |
| 后端 Mock | Python 3.11、当前 PYTHONPATH 与空配置，执行 `pytest test/workflow/test_platform_agent_contract.py test/workflow/test_platform_agent_api.py test/workflow/test_platform_agent_node.py -q --disable-warnings --tb=short --show-capture=no`。 | **34 passed、8 warnings，exit 0**，0.40s。目录／版本名称一致使用直观样例名；资源 ID、Schema、版本、模拟输出及拒绝规则未改。 |
| 前端门禁 | 当前 src/frontend 根目录执行 `pnpm lint`、`pnpm typecheck`，固定 Node 24.14.0、pnpm 9.15.9；另执行 locales build --check、check-i18n。 | **均 exit 0**。Platform 1040、Client 1727 个严格文件通过。早期 shell 自动选用 Node 20.13.1 产生 engine 警告，最终已切回 Node 24 复验。无依赖安装、锁文件修改或新增检查豁免。 |
| Vite 本地接线 | GET `http://localhost:3001/src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.tsx` 及 `/src/controllers/API/workflow.ts`。 | **exit 0**，确认本地服务实际返回单租户作用域、身份提示及多租户标志适配代码。仅证明模块接线，未冒充已登录浏览器操作。 |
| 静态及范围 | 后端两文件 Ruff；修改的前端／后端逐文件 arch-guard；三语、diff、本地文档引用、源码摘要及暂存区比较。 | 新变更无守卫报告，历史报告见前述记录。源码清单 65 项；本批 9 项既有文件变化、新增 1 项 API 测试。原有暂存内容保持不变。 |

通用 Mock 目录为「通用问答示例 (模拟)」v1／v2 和「失败与超时示例 (模拟)」各故障版本；私有样例仍只供专项 A 映射。所有模拟来源保留 EXT-01／02／03 TODO。当前页面刷新即可加载修复后的查询；中文样例名需要后端重载新代码。本次未自动重启、部署、改变真实登录合同或修改数据库配置。

用户已在本批前自行恢复工作区前端依赖，故本次前端验证直接使用当前仓库 node_modules，没有再复制到临时目录。前面的临时副本记录仅为历史环境。本次未重复无变化领域的全量回归；T039、T040 及 T048—T050 继续待执行。

### 真实环境状态（不变）

| 边界 | 状态 | 后续任务 |
| --- | --- | --- |
| MySQL／DM8、Redis、跨实例竞争 | NOT_RUN，待执行 | T048 |
| 真实昆联 API／Worker 及实际用户审计 | NOT_RUN，待执行 | T049 |
| 真实浏览器、停止及身份到期 | NOT_RUN，待执行 | T050 |
| 真实目录、身份和 invoke 替换 | WAITING_EXTERNAL | T041—T047 |

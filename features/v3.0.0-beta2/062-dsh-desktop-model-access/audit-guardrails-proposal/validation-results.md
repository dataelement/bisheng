# 模型审计开发验证结果

## 2026-10-19 正文延后持久化：本轮验证

对应 spec 0.22 AC-17、AC-35、AC-38 及 design 0.12 §4.1。仅服务端采集/后台写入优化，不变更客户端扩展协议、加密编码、正文读取协议或业务认证；保留前轮用户名展示等未提交改动。本轮没有连接109，没有修补历史缺片，没有提交、推送或部署。

- `pytest test/dsh -q -k model_audit`：**165 passed、3 skipped、573 deselected**。三个opt-in存储套件默认跳过，未算通过。新增9项请求缓冲/批量写入用例、2项HTTP/SSE阻塞和故障用例；现有模型失败、取消、迭代前关闭、ASGI发送失败、用量结算异常、完整性/来源及租户隔离继续通过。
- 5000个连续统一增量，控制队列只设4个事件名额：没有逐片段排队或存储调用，终止后只有一个正文任务；序号/单元索引/字节保留，终止、响应、用量控制事实不被片段挤占。正文消费者阻塞时控制消费者仍可完成。
- 共享预算覆盖活跃、等待和消费中的缓冲，包含块对象开销；达到预算停止审计捕获，不改写业务输出；写入完成/失败或关闭超时后退账，重复终止不重投。后台最大4个对象操作、每事务最多32个引用已断言；并发对象仍按序号入引用。
- 沿用已有隔离HTTP harness，真实FastAPI路由/ChatExecution/审计服务/仓储/加解密逻辑，合成身份与模型。模型暂停时没有正文对象或出现行；释放模型后，即使正文存储持续阻塞，SSE仍返回完整内容、`[DONE]`，模型只调用一次且用量已结算。恢复存储得到COMPLETE；注入存储失败得到PARTIAL，但模型/接口/用量仍成功。管理读取配对普通用户和越租户拒绝。按e2e-test约束不使用109凭证、不把模拟认证当正式JWT/FGA验收。
- 独立本机Docker MySQL8测试：**1 passed**（`DSH_AUDIT_GROUPS_MYSQL=1 pytest test/dsh/test_model_audit_groups_mysql.py -q`）。覆盖真实双消费者、32引用批次、一次SQL故障后有限重试、整请求重放幂等、内容COMPLETE/状态NORMAL；旧迁移与查询计划回归同时通过。对象存储为加密对象stub，不冒充真实MinIO。仅启动并清理本任务随机命名的临时容器/卷和合成数据，可重新运行创建，不操作业务库。
- Ruff、架构守卫与`git diff --check`通过；没有新增表或迁移。

**全量套件边界**：另运行完整`pytest test/dsh -q`得到548 passed、114 skipped、75 errors、3 failed（新增最后一项并发上限测试前的快照）。75项错误明确缺少`DSH_TEST_DATABASE_URL`或隔离Redis配置；不连接默认业务库补齐。三项断言失败是`test_admin_policy_view.py::test_candidates_use_configured_ids_and_target_tenant_governance`、`test_shared_trust.py::test_model_catalog_does_not_require_a_deployment_allowlist`、`test_user_grant_switch.py::test_effective_permissions_use_positive_enabled_sources[True-0-True-300]`。已用`git archive 8b79bd3cbec4a83e6192a09133fe99bbbcd9b117 src/backend`到临时目录，在同一venv/config下逐项重跑，三项同样失败，确认是HEAD既有问题；本轮不扩展修复。

**未执行门禁**：109真实模型/正式管理员身份、目标DM8、真实MinIO故障/长流并发、P95/P99和RSS。单请求16MiB与进程正文64MiB是逻辑资源上限，不是实测RSS或延迟SLA。模型终止移交前进程退出仍可丢失全部正文；本次不以同步持久化换取零缺口。

## 2026-10-19 统一筛选和会话目录：本轮验证

本节为当前实现；早期模型ID选择、四轴筛选和默认请求视图仅属历史。整体 **PARTIAL：功能及本机验证完成，正式环境与容量门禁未执行**。

- 服务端 `pytest test/dsh -q -k model_audit`：153 passed、3 skipped、573 deselected；跳过项为opt-in存储套件，不计通过。独立MySQL另行运行1项通过。覆盖状态、模式、租户/历史用户隔离、同一请求过滤、双层游标、1005会话稀疏续查、投影幂等/回滚、回填dry-run和就绪探测。目录SQL捕获无LIKE/GROUP BY/DISTINCT/COUNT。
- 临时独立MySQL8：旧表升级重放两次、三列三索引、投影回滚重投、过滤及EXPLAIN状态索引通过。仅删除本任务测试容器、卷和合成数据，可重建；未连接109或业务库。SQLite HTTP使用真实FastAPI/SQL但合成身份，不冒充正式JWT/FGA或MinIO验收。
- 前端审计API及页面9文件60项通过：默认分组、组内分页、按需原文、查看全部/返回、未关联视图、二态、聚焦候选/去重/键盘/远程分页/失败手填及旧消息解包合并回归。
- 全工作区类型检查、三语一致性、Platform生产构建通过；Ruff、架构守卫、差异检查通过。全量lint仍报6个未改文件93项错误，不标门禁全绿；改动文件单独lint，不增豁免。保留既有Ace/eval/包体警告。
- 实际组件+本机合成HTTP：桌面/窄屏聚焦候选、完整名称选择、会话仅GET元数据、显式点击单请求才POST正文、384px正文滚动均检查；只读被点开的请求，不预取第二条。不是正式登录/信创/实际供应商或性能验收。
- 新唯一迁移头dsh_audit_groups（前序dsh_audit_sources）；脚本交付但未执行业务回填。异步目录不承诺快照一致或全覆盖；正常表示当前无已知异常，未完成单独提示。
- 未提交、推送或部署。正式JWT/FGA、目标DM8、真实数据量DDL锁影响/SQL计划/长尾、并发容量与109联调仍待验收。

## 2026-10-16 已确认筛选设计实施（当前本地增量）

基于已推送提交 `f043d82ae`，用户确认筛选区与中文来源标签设计后实施。本轮只修改 Platform 展示/表单状态及三语文案，未修改服务端接口、客户端协议或存储查询；未提交、推送或更新109环境。

- **AC-49**：`ModelAuditFilters.test.tsx` 新增草稿隔离、已应用条件刷新、半开时间校验、时间确定/Esc/外点关闭、清空高级条件回归；保留模型编号/完整历史名称互斥、租户用户远程搜索分页、切租户取消旧请求等测试。待应用改动明确提示旧结果仍在展示。
- **AC-50**：模式设置默认收起，缺密钥提示仍直接可见；OFF/METADATA仍可保存，CONTENT必须有明确可用状态。HTTP API wrapper测试覆盖四种模式切换。租户管理员无配置入口，超管目录确认默认租户，身份晚到后正确加载原有范围。
- **AC-51**：消息来源只用可读标签、不输出form或来源JSON入口，重复来源kind合并；未知kind使用本地化提示。角色独立、输入参数隐藏、流式合并、正文按需读取、384px原生滚动/分段、Esc收起并归还按钮焦点均有回归。
- **自动检查**：最终10个测试文件 **73 passed**；前端根 `pnpm typecheck`（Platform553、Client1359严格文件及file-viewers）、`pnpm check-i18n`、本轮TS/TSX定向ESLint、`git diff --check`通过。Platform `pnpm build`通过，保留存量eval/大chunk提示。项目Prettier配置在当前Node下因ESM插件top-level-await加载失败，仅对本次TS/TSX使用`prettier --no-config --write`基础格式化，未改格式配置。
- **浏览器合成HTTP链路**：真实ModelAuditPanel/Filters/Mode/Card/Body通过真实请求封装访问仅监听本机的合成API。目录默认租户、无正文预取、编辑历史名称不发查询/点击查询仅发一次精确参数、无密钥时CONTENT→METADATA保存并回读、租户管理员只查租户2且无跨租户/配置入口均通过。原文source标签本地化、输出合并为助手消息、384px滚动和Esc归焦通过。1440px桌面、375px触屏、812px横屏、200%文字缩放和中英日/深色检查无横向溢出，触屏操作44px。临时合成页面、配置和服务均已清理，不是109/正式账号或真实存储E2E证明。
- **全仓lint限制**：`pnpm lint`停在Platform的 **93个现有错误**，本轮修改文件无错误。对6个报错文件分别以`git show HEAD:<path>`读取基线并重新执行ESLint，按行/列/规则/消息比对，当前93/93项均在HEAD内容上重现；未改抑制清单或无关模块，未将全仓门禁记为通过。
- **审查结论**：本轮无新增权限路径、正文预取、大表候选聚合/模糊查询或外部图片加载；复用现有bs-ui与语义色，业务组件均小于600行，新增22个键同批同步三语。剩余正式测试账号、真实存储/109、信创浏览器验收见e2e-checklist.md，整体正式E2E仍为PARTIAL。

## 2026-10-16 提交前复核：展示优化、Tab 改名与筛选设计稿

- 本次追加定向回归：9个文件 **58 passed**，覆盖卡片、正文、页面、模式（含HTTP测试）、筛选、父会话、管理API及Tab导航；前轮67项记录仍作为前轮验证快照保留。
- 前端根 `pnpm typecheck`、`pnpm check-i18n`、本次修改TS/TSX的定向ESLint及 `git diff --check` 通过。测试仍有React Router未来版本和既有Input的jsx属性警告。
- 筛选设计稿 `audit-filters-preview.html` 使用共享设计token及合成数据，不连接业务服务；1440px默认范围及筛选区域171px，375px触屏无横向溢出且按钮44px，深色模式及直接file地址加载通过。验证无密钥时仅元数据可保存、租户管理员不显示跨租户配置、高级条件收起计数、时间校验与Escape关闭。
- 本轮交付包括实际卡片展示优化和Tab改名；新版筛选区仍是待确认交互设计稿，未替换业务筛选，未更新109环境。此前未提交/未推送表述为当时的验证快照。

## 2026-10-16 请求卡片与消息展示优化

基于服务端 a9af820fc 的未提交 UI 修改；客户端无变更，未推送或重新部署 109。本轮只调整展示，不改变原文按需授权及后端数据契约。

- 定向回归：Platform 9 个测试文件 **67 passed**，覆盖新增紧凑卡片/详情无原文读取、独立状态语义、正文固定高度/键盘区域/元数据分离、1000 条消息翻段回顶且不重读原件，以及既有模式/筛选/API 回归。
- 类型与构建：前端根 pnpm typecheck、pnpm check-i18n、Platform pnpm build 通过；修改 TS/TSX 的 scoped ESLint 通过。构建仍提示存量 eval/大 chunk，测试仍提示既有 Input 的 style jsx 属性；未宣称全仓 lint 门禁全绿。
- 浏览器：独立本机合成页面渲染真实 ModelAuditCard/Body/Message，不连接业务环境。1440px 桌面上下信息各一行，正文实际高度384px、内容可滚，滚动后 footer 位置不变，区域可聚焦；375px 触屏及中英日文案无横向溢出，文字操作高度44px。浅/深色均检查；来源 kind/form 与真实角色分开显示。打开请求详情后，原文读取计数仍为1；未默认预取第二个请求正文。临时页面和开发服务器在验证后移除/停止。
- 代码审查：按 code-review 的边界、授权、并发、泄漏、测试、风格、文档七维检查本轮工作树增量；无新增权限路径或正文日志输出。复用项目现有控件、语义颜色和原生滚动；仅添加两个业务文案键并同步三语。正式账号、真实模型调用和 109 页面未在本轮验证。

## 2026-10-16 消息来源与子 Agent 增量

基线：服务端 `5ee9aca1d9`、桌面客户端 `0367d8e674` 之上的未提交修改，两端分支均为 feat/3.0.0-dsh-audit。规格 0.20、设计 0.10、客户端契约 0.4 均已确认。下面早期三存储通过记录不能替代本节新增能力的验收。

| 范围 | 实际结果与边界 |
|---|---|
| 后端审计与迁移 | **131 passed、2 deselected**；`pytest test/dsh/test_model_audit* test/database/test_alembic_single_head.py -m 'not e2e'`，含五字段/预算隔离、独立加密、权限配对、损坏标注不影响正文、101条巡检公平翻页、迁移幂等/保留回退。唯一 head 为 dsh_audit_sources |
| 实际桌面代码到 HTTP | **1 passed（memory 模式）**；Node v25.6.1 的 EnterpriseLlmAdapter + Electron parseEnterpriseChatPayload → 实际 DSH 路由/适配/队列/SQL/加密/管理读取；主/子会话各聊天与压缩共4次物理调用，无重放；存储为独立 SQLite/内存，不是真 MinIO |
| 真实 MySQL/Redis/MinIO | **环境准备未通过**；Docker 可用，但本机未缓存 MinIO，Docker Hub 拉取失败、同版本 quay.io 返回 unauthorized，尚未进入业务断言。临时 MySQL/Redis由 fixture 清理，不连接业务库 |
| Desktop 企业模块 | **211 passed、1 skipped**；`vitest run test/enterprise*.test.ts test/enterprise*.test.mjs`。随后新增末尾行分隔符和多工具图片合并的最终定向回归 **14 passed**，未把新用例数量加进先前全量结果 |
| Platform 审计回归 | **64 passed（8 files）**；覆盖 API/正文解包/来源帧/父导航/过滤/模式组件；jsdom 不是正式浏览器或 Electron 验收 |
| 类型、国际化与构建 | Desktop typecheck/build、前端根 typecheck、check-i18n、Platform build 均通过；Platform 549个 strict 文件。新增三语键一致，未手改生成错误码产物 |
| 质量检查 | 修改文件 scoped ESLint、后端 Ruff、arch-guard、git diff --check 通过；不能据此说仓库全量门禁全绿 |

复跑说明：后端采用已有项目 venv，config 只读用于导入，不修改/连接其业务存储。新增 `test/dsh/test_model_audit_sources_local_e2e.py` 仅在显式设置 `DSH_AUDIT_SOURCES_REAL_STORES=memory` 或 `1` 时执行；另设 `DSH_AUDIT_CLIENT_WORKTREE` 指向客户端审计工作树。memory 与真实 Docker 结果必须分开。真实模式可通过 `DSH_AUDIT_TEST_MINIO_IMAGE` 指定可用测试镜像；仅允许本地 Unix Docker、随机自建实例及 loopback。桌面 `scripts/verify-audit-sources.mjs` 只连接 health.fixture=true 的本机服务，当前 Node 用原生 TS 类型擦除导入纯主进程校验器；正式应用不依赖该探针。

扩大检查仍有未通过项：

- 后端全量初跑4 failed/508 passed/103 skipped/75 errors；新能力声明的旧预期已更新并由定向复跑覆盖。排除 external 后为3 failed/511 passed/103 skipped/81 deselected/5 errors；错误要求独立 SQL/Redis 配置，失败位于未修改的 test_admin_policy_view、test_shared_trust、test_user_grant_switch。本轮未跑干净基线，不能武断断言这3项都是既有失败。
- Platform 全量 lint 为93 errors，输出文件均未被本轮修改；scoped lint 通过。扩大 DSH 页面测试183 passed/1 failed，commercialLicense.test.tsx 单独也失败：测试仍期待旧的“DSH Enterprise License Request”，实际文案是“Client Enterprise License Request”。该组件及测试未改，不扩大本轮修复范围。
- 最初直接 tsc 会检查冻结旧文件，不作为项目类型门禁结论；正式结论为根 pnpm typecheck 使用的 tsc-strict。Prettier 旧配置的 CJS require 遇 ESM 插件失败，使用已安装 Prettier 的空配置仅格式化本次文件，不修改配置、依赖或抑制基线。

L1/L2：按 task-review/code-review 检查未提交增量的分层、边界、授权、并发、泄漏、测试和文档，不只看 HEAD diff。修复了标注巡检页饥饿与 JS `$` 可接受末尾换行的差异，均有回归。正式 Electron 会话 resolver 生命周期/重启、安装后插件闭包、浏览器窄屏/信创、Linux DM8、真实供应商/Gateway身份及三存储压力/故障仍未执行。当前结论：核心代码及受控 HTTP 链路完成，完整环境验收 **PARTIAL**。未提交、推送、部署或删除业务数据。

---

2026-10-15 合并 `feat/bisheng-work-103` 及单迁移头修复的最新证据见 [分支合并验证](./merge-validation-20261015.md)。以下保留 2026-10-14 开发验收的历史快照，不代表合并后已重新部署或完成全面门禁。

日期：2026-10-14。结论：功能代码、本机隔离存储及双端代码联调通过；发布验收 **PARTIAL**。未提交、推送、合并或部署。

## 1 环境与证据边界

- 服务端工作树：`bisheng/.worktrees/feat-3.0.0-dsh-audit`，分支 `feat/3.0.0-dsh-audit`，原开发基线 `eb41b17868dfd706b93fc4df27d8d09ed10960ee`。当前本地 `origin/feat/3.0.0` 已前移至 `e058f58eb8d03cf582725d31e194eeeb16fce205`；没有自动合入或覆盖用户工作，发布前须同步发布线后再回归。
- 客户端：`bisheng-work/.worktrees/feat-3.0.0-dsh-audit`，同名分支，独立 agent 基于 `origin/main=3f6f010b280e7e095a13f59d8e3faae2c6223ab2` 开发。
- 根据用户授权启用本机 OrbStack，使用已缓存 MySQL 8.0、Redis 7.2、MinIO 镜像创建唯一命名、loopback 端口、`bisheng.test=dsh-audit` 标签的独立容器。数据库、私有测试 bucket、密钥和合成身份均临时生成，不使用业务库或生产凭证。
- `test/dsh/audit_local_server.py` + `model_audit_harness.py` 使用真实 DSH route/service/adapter/queue/writer/repository/AES-GCM/MinIO 代码；身份、模型、准入与用量事件生产者是合成设施。真实平台 JWT/OpenFGA/Gateway、供应商响应、正式 Electron 窗口不在此证据范围内。
- Python/ruff 复用主检出 venv 的安装，导入当前工作树源代码；主检出 config.yaml 只读用于 import，不修改配置，不连接其业务存储。外部回归明确使用独立 `dsh_test_` 库和测试 Redis 索引。

## 2 自动化与质量门禁

| 范围 | 实际结果 | 解释 |
|---|---|---|
| 审计定向 + 运行时注册 + SQL 可移植性 | **103 passed、2 skipped、1 deselected** | `test_model_audit*.py`、`test_operations_runtime.py`、`test_sql_portability.py`，`-m 'not e2e'`；2 skip 是真实 DM 编译器不可用，单独 opt-in HTTP 用例不混入单元结果 |
| 本机 HTTP + 真 MySQL/Redis/MinIO | **1 passed（最终复跑 0.56s）** | `test_model_audit_e2e.py`：两次流/非流调用、稳定会话顺序、两类管理员读取、普通用户/跨租户拒绝、逐次原文 no-store、输入扩展剥离；合成 bearer 并非生产 JWT 验收 |
| 客户端→最新服务端真存储 | **1 passed（最终复跑 830ms）** | 全新临时实例，真实 EnterpriseService→插件→适配器→broker→主进程→HTTP，核心 5 次请求 + 2 次精确 ID 探针；7 条 CONTENT COMPLETE，原文 NDJSON COMPLETED |
| Platform API/原请求兼容/NDJSON/导航/组件 | **22 passed（5 files）** | 默认无原文、按需单次读取、切页清理、模式权限展示、缺口解释、1000 片原文分段且只读一次 |
| 全前端 `pnpm typecheck` | **通过** | Platform 533 strict files、Client 1357 strict files、file-viewers |
| `pnpm check-i18n` | **通过** | 新文案/错误码三语一致；生成错误码文件通过共享 locales 构建，不手改生成件 |
| Platform `pnpm build` | **通过（最终构建 16.35s）** | 8282 modules，包含原文分页实现；保留既有 ace/eval/大 chunk 警告 |
| 修改文件 ESLint / ruff / arch-guard / diff-check | **通过** | 无新增架构发现；prune 缩减 6 行 request.ts 旧 suppression |
| Platform 全量 ESLint | **93 个既有 error，未通过** | 与干净 HEAD 存档的文件、规则及数量完全一致，没有新增 error；不能宣称全量 lint 绿灯 |
| 全 DSH 回归（干净原基线） | **546 passed、7 failed、6 skipped、8 deselected** | 在另外的独立空库、Redis 索引重跑对照 |
| 全 DSH 回归（当前分支快照） | **633 passed、7 failed、6 skipped、9 deselected** | 最终空库 89.59s；7 个失败逐个与原基线一致。之后补充的历史分块读取、惰性编码及原文流末尾关闭回归另在上述 103 项定向组合验证通过 |

重用测试库时 `test_existing_user_additive_migration` 曾因 user 表已存在按设计拒绝运行。未删除旧库或 user 表；改用新的 `dsh_test_audit_final_clean` 空库重跑后该环境失败消失。它不是新增功能回归。

### 既有失败与 lint 对照

全 DSH 的 7 个既有失败：

1. `test_admin_policy_view::test_candidates_use_configured_ids_and_target_tenant_governance`：既有模型展示名与测试别名预期不同。
2. `test_mixed_policy_recovery::test_mixed_grants_save_and_recover_original_operation` 的 sqlite/external × False/True 四项：既有跨根租户角色策略预期 300，实际 0。
3. `test_shared_trust::test_model_catalog_does_not_require_a_deployment_allowlist`：既有模型展示名差异。
4. `test_user_grant_switch::test_effective_permissions_use_positive_enabled_sources[True-0-True-300]`：同类既有跨租户角色源问题。

Platform 93 个既有 error：CitationReferencesDrawer 2、controllers/API/index.ts 63、API/license.ts 3、WorkbenchSensitivePolicy 3、FlowChat/MessageMarkDown 6、f067LicenseBannerCopy.test.ts 16。没有修改这些无关逻辑或添加 suppression 掩盖失败。

### 复现命令

在服务端 `src/backend`，使用本机已有 venv 或 uv 安装的等价环境：

```sh
python -m pytest test/dsh/test_model_audit*.py test/dsh/test_operations_runtime.py \
  test/dsh/test_sql_portability.py -m 'not e2e' -q
python -m test.dsh.audit_local_server --real-stores
```

另一个终端，仅从 fixture 输出取得临时合成 token，设置 `DSH_AUDIT_LOCAL_FIXTURE=1`、`DSH_AUDIT_BASE=http://127.0.0.1:8786`、`DSH_AUDIT_ADMIN_TOKEN`、`DSH_AUDIT_TENANT_ADMIN_TOKEN`、`DSH_AUDIT_USER_TOKEN` 后运行：

```sh
python -m pytest test/dsh/test_model_audit_e2e.py -m e2e -q
python scripts/measure_dsh_model_audit.py --base http://127.0.0.1:8786 --apply --samples 10
```

脚本无 `--apply` 仅 preflight；BASE 必须 loopback 且 health.fixture=true。完整 DSH 外部回归另需 `DSH_TEST_DATABASE_URL`（新空 dsh_test_ 库）、`DSH_TEST_DATABASE_ISOLATED=1`、`DSH_TEST_REDIS_URL`、`DSH_TEST_REDIS_ISOLATED=1`，Redis AOF only in owned test container。不要复用业务库，也不要把 token 写命令历史、文档或输出文件。

前端从 `src/frontend` 执行 `pnpm typecheck`、`pnpm check-i18n`；定向 Vitest 从 Platform 执行：

```sh
pnpm exec vitest run src/controllers/requestStream.test.ts \
  src/controllers/API/dshModelAudit.test.ts src/controllers/dshRequestCompatibility.test.ts \
  src/pages/SystemPage/dsh/ModelAuditPanel.test.tsx src/pages/DshPage/dshPageNavigation.test.tsx
pnpm exec vite --config test/model-audit-vite.config.ts
```

## 3 已验证行为

统一接口包含参数、工具定义/选择、按序消息、实际工具调用/结果、inline image、reasoning、非流式返回及流式 delta/finish。疑似凭证文本如果真在模型输入中仍忠实保存，传输 token 与 audit_context 不入正文。OFF/METADATA 无原文，配置读取失败 OFF 不沿用旧值。

模型成功、ASGI 响应中断、结算不确定可同时存在；取消/失败留存完整观察边界可为 COMPLETE。乱序、重复、缺尾片、清单缺失、对象故障、预算耗尽不造完整；迟到事实可恢复 UNKNOWN/PARTIAL。独立线程池与队列上限、有限关闭、Redis 代次与迟到 set/finish、历史 OFF 后状态扫描均有组合验证。

正文 AES-GCM + scope HMAC，仅在同租户/用户/CONVERSATION 或 REQUEST 作用域内候选复用。对象写后回读核验，再建 READY 引用；SQL 没有正文。读取先按历史记录租户授权并提交 durable attempt，日志失败不能出任何正文，流中断不会改写服务端原件状态。

页面默认卡片且分页、无正文预览；精确定位第二轮请求后点击原文显示其实际历史与输出。切“本用户会话”清空请求过滤，按四次实际先后显示聊天/聊天/压缩/标题四卡。UTC 返回和 MySQL 微秒时间已修复。长原文按最多 100 个 frame 分段显示，保留完整流、翻页不重新授权读取；收起/切页清理原文和 Abort。

## 4 D-09 正常小样本（不设 SLA）

同一本机、相同合成上游，每模式 10 次串行流式请求，正文约 16 KiB，生产默认 16 KiB 分块。独立 fixture 模型 entered 计数增量 **30**，提交 **30**，开启模式期望 **20**、元数据可见 **20**；CONTENT 期望 **10**、完整 **10**；OFF 不入审计分母，无模型重放。切模式后恢复初始 CONTENT。

| 模式 | 首个内容 P95 | 总响应 P95 | 元数据可见 P95 | 正文完整可见 P95 | 固定 Token 基线可见 P95 |
|---|---:|---:|---:|---:|---:|
| OFF | 9.704ms | 16.372ms | 不适用 | 不适用 | 18.467ms |
| METADATA | 21.109ms | 32.753ms | 53.172ms | 不适用 | 41.608ms |
| CONTENT | 10.527ms | 26.498ms | 37.548ms | 116.866ms | 33.485ms |

P99 与 P95 相同，因为每组只有 10 次、采用 nearest-rank；不是有统计把握的回归上限。轮询间隔 25ms，还包含 HTTP 观察延迟。Token 基线固定为已有 **dsh_model_call 持久明细**，使用同一合成生产者；不是 Redis allowance，也未假称真实 Token 页面端到端时延。进程 peak RSS 797491200 bytes，测量期间峰值增量 0；包含框架/模型 import 的既有峰值，不能推断“审计零内存”。首个 CONTENT 例 `2c6bef24-aae2-4517-a8fe-ccc0a971229e`，末例 `15e22073-043d-42ad-ab9c-5393bdc53caa`。

失败/取消/模式降级/全失写已做功能故障测试，但本轮没有并发长流、压力满载、这些故障类别的完整量化时效与覆盖率报告。T065/T066 保持部分完成，不能把正常小样本覆盖率推广到生产或故障运行。

## 5 仍需外部或正式验收

- Linux 真 DM8：仓储、索引、并发和 MinIO/Redis 故障组合；当前仅通用/MySQL SQL 编译及本机 MySQL 实测。
- 同步前移的发布线后重新门禁；修复/处置 7 个既有后端失败和 93 个既有 lint error。
- 正式 Platform 登录与 JWT/OpenFGA/受限 Child 管理范围、真实供应商/Gateway、实际 Electron/Fork/并行 Agent/Windows 安装。
- D-09 并发长流与故障分类量化、容量持续增长、密钥轮换/备份恢复运维演练。
- 窄屏 375px 试图通过浏览器 viewport 工具验收时连接不可达，已恢复默认设置；不标通过。默认桌面实际页面已验收并保存截图。

已正常关闭 fixture 与两个本任务预览进程，并核对 dsh-audit 标签容器为空、8786/3301/3302 无监听；临时测试容器、测试卷和合成数据已清理，不可直接恢复但可重新生成。不保留业务凭证，不删除业务数据，不停止用户的容器引擎或其他服务。保留源码、报告和合成请求编号即可按说明重新生成环境。
# 2026-10-15 模型精确查询补充验证

- AC-21：模型候选仅查询授权租户的当前开放目录，不进入审计 Repository；同名不同 ID 保留独立候选，普通用户/跨租户请求在目录读取前拒绝。HTTP 验证沿用隔离 audit harness，身份与模型目录为合成数据，不代表线上账号联调。
- 名称与模型 ID 互斥；历史名称使用原始 UTF-8 摘要及原值双重等值校验，覆盖字面 `%/_`、大小写/尾空格、同名不同 ID、改名前后记录、租户隔离、相同时间游标分页；SQL 捕获断言模型查询不包含 LIKE、DISTINCT 或 COUNT。
- 后端审计测试及单迁移头检查：119 passed / 1 skipped；跳过项为既有 opt-in 全存储 HTTP 联调，不计作通过。Alembic 唯一头为 `dsh_audit_model_lookup`。
- 前端 7 个相关测试文件：59 passed，覆盖模型选择后提交 ID、手填清除 ID、清空/重置、分页/搜索/失败重试、无效候选以及之前的 HTTP 保存与默认租户修复。三语文案按 i18n-localizer 同步，类型检查、国际化一致性检查及平台生产构建通过。
- 本机独立 Docker MySQL 8：实际执行新增列/索引迁移两次，5000 条合成记录分租户回填，dry-run 不写及重跑幂等通过；EXPLAIN 的模型 ID 与名称摘要查询分别使用 `ix_dma_request_model`、`ix_dma_request_name`，访问类型均为 ref，样本预计读取 33 行。该数据量不是性能 SLA。临时容器及合成数据已删除，未连接业务库。
- 全量 pnpm lint 仍报 93 项错误，均在 6 个与 HEAD 完全一致的未修改文件；lint 配置及 suppression 也未改动。本次修改的前端文件独立 ESLint 通过，不为绕过基线添加豁免。
- 未部署 109、未对业务环境执行 DDL/回填；历史名称查询交付前须按 audit-rollout.md 完成逐租户摘要回填。DM8 实机性能/执行计划仍待中央回归。

## 本轮页面验收清单

- [ ] 超管进入页面默认选择默认租户，租户管理员直接加载本范围；切换租户清空模型、用户、游标与原文。
- [ ] 下拉只展示当前开放模型，选择后按 ID 查询，模型改名前的记录也能返回。
- [ ] 修改输入框为完整历史名称，按名称精确查询；前缀、大小写或空白不同不匹配，删除配置后仍可查询已回填记录。
- [ ] 清空/重置后移除 ID 与名称条件；候选失败仍可手填，不将错误误报成无记录。
- [ ] HTTP 环境无密钥仍能保存 OFF/METADATA；仅 CONTENT 受密钥就绪校验限制。

# 2026-10-15 消息解包与流式合并验证

本轮替代早期“逐 frame 展示 JSON”的阅读实现，不改变采集、存储、授权接口和查看留痕。按 AC-10、AC-12、AC-14、AC-19、AC-21 修正：首条非消息参数单元不进入阅读区；系统/用户/历史助手/工具结果按原顺序解包；同请求输出增量合并，思考独立折叠，工具调用按索引合并并保留编号；不跨请求推断或去重气泡。

- 前端9个相关测试文件共76项通过。新增10项组装测试和7项真实 NDJSON 解析到 UI 的合成数据测试：分片 JSON、2000个输出增量、流式/非流式、并行工具索引、多模态顺序、缺片/损坏、读取中断、NOT_CAPTURED 不误判缺口、20Mi字符预算、长文本分页、租户切换取消、HTML/脚本/远程图片不执行不自动加载。1000条输入消息每页最多100条；单条超过16000字符可切段，不丢尾部、不重复 POST。
- 类型检查、三语一致性/生成产物检查、生产构建、所有本轮前端文件独立 ESLint、架构守卫和 diff 检查通过。既有 React jsx/router、Ace/eval/chunk size 警告仍存在；全量 lint 仍为6个未修改文件中的93项基线错误，未添加豁免或修改基线。
- 使用独立浏览器上下文打开本机 `test/model-audit-preview.html?view=messages`，只使用合成消息和实际组装/消息呈现组件，不登录、不调用109、不读取业务原文。桌面1280px与375px窄屏确认5条有序角色消息、首条参数隐藏、输出只显示一条合并回复、思考默认收起且可展开、工具编号一致、无横向溢出、无外部资源请求；375px下150%字体仍无横向溢出。该预览不替代正式平台登录验收；暗色主题宿主与完整正文访问授权链路本轮未做真实环境页面验收。
- 未修改服务端，无新迁移；本轮验证未连接或重新部署109，不重复使用测试账号或生产凭证。

## 消息阅读部署后验收清单

- [ ] 在109正常登录，明确展开一条流式审计记录，确认只见角色/消息内容、不再逐条显示 delta 或首条参数块。
- [ ] 对照同一请求的系统/用户/历史助手/工具输入，核对顺序与工具调用编号；输出内容和思考分别合并、不丢字重字。
- [ ] 展开长历史/长回复并翻段，核对末尾仍可读，翻段不新增正文访问请求；收起/切租户不残留原文。
- [ ] 有 PARTIAL/gap 时显示缺口；仅浏览器读取中断时只标读取/消息显示不完整，不改变服务器留存状态；METADATA 无正文不误报缺口。
# 2026-10-19 父子会话嵌套增量

规格0.23、设计0.13经用户确认后已实现。新增层级目录/路径、独立任务、同请求筛选与父子UI，原始审计、模型调用和用量不合并。

本轮后端回归246通过/12跳过、相关页面24通过、独立MySQL通过、全量typecheck与check-i18n通过；全量既有lint和License失败、正式环境/DM8/容量未执行项见[audit-hierarchy-e2e.md](./audit-hierarchy-e2e.md)。浏览器真实组件在375px父子展开无横向溢出，Enter可展开，零正文预取。只提交推送，不部署109，不以历史用例代替本轮证据。

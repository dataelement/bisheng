# 模型审计开发验证结果

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

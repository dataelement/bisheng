# F121 实施与验证记录

2026-11-06 在 `codex/kunlian-integration` 实施 T001–T021。本地验证使用当前工作区、现有 Python 3.11.14、独立空测试配置、隔离 SQLite 和现有前端依赖。T022–T025 保持待执行。正式候选接口的路径及凭据合同仍待双方确认。

## 批次记录

| 证据 | 批次及实际命令 | 结果 |
| --- | --- | --- |
| E-001 | W0／W1，`pytest test/workflow/test_kunlian_workflow_management.py -q` | 2 passed。新模型在隔离 SQLite 建表，验证同请求重试、所有者投影失败恢复、复用配额判定及过期草稿拒绝。真实建表待执行。 |
| E-002 | W2，`pytest test/workflow/test_kunlian_workflow_{management,publication}.py test/workflow/test_platform_knowledge_publication.py -q` | 5 passed。验证发布与变更同事务回滚、V2 替换、固定资料、下线及同版重发。 |
| E-003 | W3，`pytest test/workflow/test_kunlian_workflow_{management,publication,registration_sync}.py test/workflow/test_workflow_action_map.py test/workflow/test_platform_knowledge_versions.py -q` | 12 passed。覆盖游标防篡改、消费范围、窗口、续取、撤销回执及相关版本回归。全量期间撤出及保留点重建用例随后纳入 E-004。 |
| E-004 | W4 后端，`pytest test/workflow/test_kunlian_workflow*.py test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py test/workflow/test_workflow_action_map.py test/sso/test_kunlian_ws_admission.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings --tb=line --show-capture=no -rs` | 128 passed，3 skipped，退出 0。跳过 F119／F120 的实际 API、Broker、Worker 和独立 Redis 用例。 |
| E-005 | 最后增加模拟消费者持久检查点后，`pytest test/workflow/test_kunlian_workflow_registration_e2e.py -q` | 1 passed。隔离 ASGI 调用现有创建、版本、发布、旧下线路径和候选拉取接口。模拟消费者用临时 SQLite 在同一事务更新目录和检查点，并重新连接读取。覆盖回放、撤权、V2 替换、下线和回执补偿。 |
| E-006 | Platform Vitest 运行 `platformKnowledge.test.ts`、`workflow.test.ts`、`createAppTemplate.test.tsx`、`hostedAppStateFilter.test.tsx`、`RunTest.platformKnowledge.test.tsx`、`PlatformKnowledgeQueryItem.test.tsx`、`PlatformKnowledgeSelectItem.test.tsx`、`PlatformAgentItem.test.tsx` | 31 passed，退出 0。覆盖旧页面回归、创建重试复用请求键、草稿修订请求头。 |
| E-007 | Platform `pnpm --filter bisheng typecheck`、修改文件定向 ESLint、locales 生成产物校验和 `node scripts/check-i18n.mjs`。后端新增文件 Ruff、既有入口 F821 检查、架构守卫和 `git diff --check` | 通过。原暂存差异校验值仍为 `2c02efc7a00787416da5ad7fac3ede4c3c14c539576124b8c9f46b5de59a3e91`。 |

## 本地行为与限制

- 创建复用既有入口。Mock 显式启用的租户中，可通过 `/build/apps?kunlian_workflow=new` 打开既有创建对话框。请求键用于同一次创建的恢复，草稿修订用于拒绝陈旧保存。开启配置及准备数据库属于后续环境步骤。
- 发布与下线记录在 Workflow SQL 事务内。候选端点具备版本资料、快照、变更和回执能力，由隔离测试应用装配。候选身份依赖默认拒绝，测试通过依赖覆盖注入用户和同步器。发布登记状态与工作流状态分别展示。
- 本地资料合同暂支持单个文本表单及单个无交互文本输出，也支持无输入的文本输出流程。复杂业务 Schema 和正式同步时限保留 `TODO [F121]`。保留点与失效处理已测试，生产保留期限和实际清理安排待确认。
- 隔离 API 测试运行现有工作流图初始化及 API 入口。实际用户身份、F048 决策及非本地服务使用测试夹具。该证据不替代真实 F118、OpenFGA、浏览器和昆联同步。

## T001–T021 审查与回归

2026-11-06 对照规格、设计和任务复查本地实现。以下用例先在修复前复现，再用于回归。

| 发现 | 验收与任务 | 复现及预期 |
| --- | --- | --- |
| P1 跨租户入口未统一校验目标租户 | AC-06，T006、T007、T013 | 将 F048 动作设为允许，访问另一个租户已纳入登记的工作流。详情、版本读写及旧元数据入口必须拒绝。版本读取须按所属工作流核验租户，即使历史版本行写入了不同租户。 |
| P1 管理列表误依赖租户字段 | AC-05、AC-06，T006、T021 | 复用现有列表的真实字段结构时，原候选列表拒绝正常记录。改为批量核对归属，再逐条复核查看权，过滤越界项。 |
| P1 旧请求能下线无登记投影的当前版本 | AC-11，T011–T013 | 已在线的存量工作流以 V2 为当前版本。携带 V1 下线必须冲突，V2 保持在线。 |
| P1 发布提交未复核工作流登记资格 | AC-09，T012 | 在预检完成后撤出配置中的工作流。提交必须冲突，工作流保持原状态且流序号不增加。 |
| P1 实际版本失效后仍返回登记资料 | AC-10、AC-11，T014、T018 | 将已登记版本切成非当前或软删除。版本详情和全量目录须判定不可用，旧成功回执不得覆盖补偿状态。 |
| P1 变更缺号时仍推进检查点 | AC-11，T017 | 从保留区间移除一条记录。读取遇到缺口时要求重扫，不返回可跨过缺口的检查点。 |
| P2 分页续签刷新原扫描有效期 | AC-11，T016、T017 | 在临近过期时翻页。后续分页必须遵守原扫描或增量窗口截止时间，日常增量仍可从持久检查点开新窗口。 |
| P2 旧下线路径绕过审计钩子 | REQ-10，T013、T021 | 在有下线权限的旧入口执行下线。写入下线变化后应继续执行原有审计钩子。 |

T021 模拟消费者将待回传结果、目录和检查点一并提交到临时 SQLite。回执请求失败后重新连接，检查点仍可用，待回传结果可独立补偿。同一变化补偿成功后，延迟的失败回执不能改变终态。

### 审查执行证据

| 证据 | 范围及实际命令 | 结果 |
| --- | --- | --- |
| E-008 | 修复前，选跑 `test_kunlian_workflow_{publication,registration_sync,registration_e2e}.py` 中与上表对应的用例 | 观察到跨租户接口返回成功、旧版本下线未拒绝、无效版本仍给出资料、缺号未报错、窗口被续期、正常列表返回拒绝、撤出范围后仍发布和旧下线遗漏审计。 |
| E-009 | 空测试配置下扩展 E-004 加入 `pytest test/tenant/test_tenant_filter.py`，并单独复跑该文件 | 单文件 6 failed，2 passed。失败发生在用例给 `Settings.multi_tenant` 赋值时，旧校验器将空 Redis URL 列表传给正则表达式。临时测试配置为两个 Redis URL 提供回环占位值后，单文件 8 passed。 |
| E-010 | 修复后用临时配置运行 `pytest test/workflow/test_kunlian_workflow*.py test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py test/workflow/test_workflow_action_map.py test/tenant/test_tenant_filter.py test/sso/test_kunlian_ws_admission.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings --tb=line --show-capture=no -rs` | 149 passed，3 skipped，退出 0。其中 F121 21 项。跳过需要实际 API、Broker、Worker 或独立 Redis 的 F119／F120 用例。 |
| E-011 | F121 文件 `ruff check`、`ruff format --check`，既有入口 `ruff check --select F821`，架构守卫，`git diff --check` | 通过。架构守卫保留两个既有路由的 RULE-3 告警。暂存区校验值与 E-007 一致。 |

## T026–T034 工作流管理页验证

2026-11-10，分支 `feat/v3.0.0/118-kunlian-integration`。后端使用工作区 Python 3.14.0、独立测试配置和 SQLite。浏览器使用隔离 Chrome 配置，Vite 与 Mock HTTP 服务仅监听回环地址。浏览器侧的授权、会话及接口响应由夹具提供，服务端租户、路由权限与持久创建行为使用单独的后端用例核对。

| 证据 | 批次 | 验证结果 |
| --- | --- | --- |
| E-012 | W6 管理页与列表 | 实际 SQLite 应用列表扫描排除根租户、其他租户及其他类型，拒绝普通列表游标。Platform Vitest 核对状态筛选、搜索参数和工作流范围。浏览器验证工作流卡片、第二页及搜索无结果。 |
| E-013 | W7 只读、编辑与返回 | 隔离 ASGI 验证只读摘要裁剪、拒绝直接读取画布、撤销查看权后拒绝旧地址。浏览器验证查看者进入只读详情、编辑者进入画布。刷新画布后修改节点，点击返回可取消并保留草稿，选择不保存则回到工作流管理页。 |
| E-014 | W8 新建与幂等 | 隔离 SQLite 验证两个同键请求复用原工作流与初始版本，同键异参拒绝，所有者投影失败后恢复，管理页创建不自动纳入发布登记。隔离 ASGI 验证无创建权限直接提交返回 403。浏览器验证无创建权时隐藏入口，以及提交失败后重试复用同一 `Idempotency-Key`，只得到一个工作流并进入画布。 |
| E-015 | W9 SSO 与浏览器闭环 | `node tmp/f121-management.kcPY3xEq/browser.mjs` 退出 0。Mock F118 授权回调保留 `/build/workflows`，已有会话直达。取消授权及失败回跳显示登录页，自动跳转计数不再增加。浏览器临时脚本在本地忽略目录中。 |
| E-016 | 相关回归与静态检查 | 后端 361 passed、7 skipped，退出 0。跳过用例依赖专用 API、Broker、Worker 或本地 Redis。Platform Vitest 30 passed，定向 ESLint、严格类型检查和三语校验通过。后端 Ruff 与架构守卫通过，守卫输出既有 `workflow.py` RULE-3 告警。`git diff --check` 通过。 |

后端回归命令在 `src/backend/` 执行，`config` 指向隔离测试配置。

```bash
config=/tmp/bisheng-f121-tenant.13VxuE .venv/bin/python -m pytest \
  test/workflow/test_kunlian_workflow*.py test/api/test_build_managed_tenant_scope.py \
  test/api/test_workflow_list_cursor.py test/api/test_workflow_list_visible_first.py \
  test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py \
  test/workflow/test_workflow_action_map.py test/tenant/test_tenant_filter.py \
  test/sso/test_kunlian_ws_admission.py test/open_api/test_workflow_invoke_input_errors.py \
  -q --disable-warnings --tb=short --show-capture=no -rs
```

Platform 回归命令在 `src/frontend/` 执行。

```bash
pnpm --filter bisheng exec vitest run src/test/createAppTemplate.test.tsx \
  src/test/hostedAppStateFilter.test.tsx src/test/kunlianLogout.test.tsx \
  src/controllers/kunlianSession.test.ts --maxWorkers=1 --minWorkers=1
pnpm --filter bisheng typecheck
node scripts/check-i18n.mjs
```

本地实现复用了现有 `workflow_kl_creation` 表。管理页的创建键使用独立前缀，历史登记键继续按原格式解释。旧版图保存回归的 SQLite 夹具补齐了此表，浏览器会话夹具和 API 权限夹具分别提供身份，真实授权服务的结果留在 T035／T036。

## T026–T034 审查与修复

2026-11-10，在 `feat/v3.0.0/118-kunlian-integration` 的工作区对照规格 AC-13–AC-17、设计 §4.6 和补充任务审查。沿用前一节的隔离 Python、SQLite 和 Chrome Mock 环境。

| 发现 | 对应验收 | 修复与复核 |
| --- | --- | --- |
| P1 旧更新入口仅凭 `edit` 可更改普通工作流的上线状态，管理页卡片也错误地依赖该编辑入口 | AC-15，T028–T029 | 旧入口按目标状态核验 `publish` 或 `unpublish`，拒绝无效状态。管理页先从当前租户的只读摘要取得当前版本，再使用原有版本状态接口。仅具备查看和对应状态动作的用户可操作，编辑权不会替代状态动作。 |
| P1 并发同键创建在最后一个配额被前一请求使用时返回配额错误 | AC-03、AC-16，T031 | 遇到租户或角色配额不足时重新查询同一主体、请求键和请求摘要。已有创建结果则恢复原对象和初始版本，其他创建请求继续受配额限制。 |
| P1 F118 回调后的会话检查遇到 `SESSION_EXPIRED` 时再次自动发起 SSO | AC-13，T033 | 普通未登录与结构化过期分支共用本次导航的自动发起标记。回调、已尝试或错误回跳时保留手动重试入口，重试只带管理页目标路径。管理入口跳过旧的 URL 参数写入登录 Cookie 路径。 |
| P2 列表查询后补充版本摘要等字段时已退出管理页租户范围 | AC-14，T026 | 将补充字段查询放在同一租户上下文，结束后恢复原查询范围。原普通列表沿用既有上下文。 |

| 证据 | 实际执行 | 结果 |
| --- | --- | --- |
| E-017 | 后端管理和登记 ASGI 测试选跑 `-k 'last_quota or legacy_status_patch'`。前端 `kunlianSession.test.ts` 选跑管理页首次登录和回调过期。 | 修复前后端 3 项按预期失败。旧接口返回 200 并改变状态，并发重复创建返回配额错误。前端回调过期用例观察到第二次授权跳转。 |
| E-018 | 后端定向执行 `test_kunlian_workflow_management.py`、`test_kunlian_workflow_registration_e2e.py`、`test_kunlian_workflow_authorization_e2e.py`、`test_build_managed_tenant_scope.py` 和 `test_workflow_list_cursor.py`。 | 32 passed，退出 0。覆盖租户上下文恢复、状态动作允许和拒绝、同键并发及授权回归。 |
| E-019 | Platform 运行 `kunlianSession.test.ts`、`kunlianLogout.test.tsx`、`hostedAppStateFilter.test.tsx`、`createAppTemplate.test.tsx`、`dshLoginReturn.test.ts`，单 Worker。 | 41 passed，退出 0。覆盖查看者与独立发布权限、当前版本、回调过期与历史回退、手动重试目标和旧登录入口兼容。严格类型检查、定向 ESLint、三语校验通过。 |
| E-020 | `node tmp/f121-management.kcPY3xEq/review-browser.mjs` | 隔离 Chrome 退出 0。保留原列表、详情、新建和画布回归。增加旧回跳目标残留、错误回跳后手动授权和回到无错误参数的管理页验证。脚本保留在本地忽略目录。 |
| E-021 | 修复后复用 E-016 的后端回归命令。运行 Ruff、定向架构守卫和 `git diff --check`。 | 364 passed、7 skipped，退出 0。跳过原因同 E-016。静态检查通过，架构守卫保留既有 `workflow.py` RULE-3 告警。 |

## 测试服务器目录映射部署

2026-11-11 用户授权部署后，在 `192.168.106.104` 采用源码目录映射完成部署，入口为 `http://192.168.106.104:3001/build/workflows`。后端复用已有依赖，Platform 和 Client 用 Vite 运行。配置、操作命令和回退方式见 [部署记录](./deployment-20261111.md)。

| 证据 | 实际执行 | 结果 |
| --- | --- | --- |
| E-022 | 服务器源码 SHA256 校验、Compose 与 Nginx 配置检查、容器健康检查，以及浏览器现有管理员会话操作。 | 5821 个文件与源码快照一致。管理页、现有工作流画布、取消新建及返回管理页通过，Client 加载通过。重启网关处理旧后端地址缓存后，管理页所观察到的 API 响应均成功。 |

E-022 为实际部署后的管理员冒烟证据，T035、T036 的完整权限、并发和双方 SSO 验收继续为 `NOT_RUN`。

## 待执行

| 项目 | 状态 | 条件 |
| --- | --- | --- |
| 正式身份、接口、Schema 和回执契约 | WAITING_EXTERNAL | EXT-01、EXT-02、EXT-03、EXT-05，T022／T023。 |
| MySQL／DM8 提交顺序、并发锁、真实权限投影和浏览器 | NOT_RUN | T024，专用数据库、OpenFGA、F118 和测试账号。包括删除与发布并发时权限投影和工作流状态的核对。 |
| 昆联同步器、工具目录、真实下线传播和回退演练 | NOT_RUN | T025，双方测试环境和验收时效。包括停用与恢复时目录撤出和历史版本保留。 |
| 管理页真实数据库与 OpenFGA | NOT_RUN | T035，需受控 MySQL／DM8、OpenFGA 及有查看、编辑、创建差异的账号。核对跨租户过滤、创建并发和撤权。 |
| 昆联「工作流管理」按钮及真实 SSO | NOT_RUN | T036，需联调 Origin、昆联按钮 URL、F118 回调登记和已同步授权的测试账号。 |

本轮未执行业务数据库建表、迁移、运行配置启用或部署。

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

## 待执行

| 项目 | 状态 | 条件 |
| --- | --- | --- |
| 正式身份、接口、Schema 和回执契约 | WAITING_EXTERNAL | EXT-01、EXT-02、EXT-03、EXT-05，T022／T023。 |
| MySQL／DM8 提交顺序、并发锁、真实权限投影和浏览器 | NOT_RUN | T024，专用数据库、OpenFGA、F118 和测试账号。包括删除与发布并发时权限投影和工作流状态的核对。 |
| 昆联同步器、工具目录、真实下线传播和回退演练 | NOT_RUN | T025，双方测试环境和验收时效。包括停用与恢复时目录撤出和历史版本保留。 |

本轮未执行业务数据库建表、迁移、运行配置启用或部署。

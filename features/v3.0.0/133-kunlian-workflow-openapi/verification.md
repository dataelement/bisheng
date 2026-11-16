# F133 实施验证记录

- Status：IN_PROGRESS / NOT_READY
- Date：2026-11-16
- 基线：4e37058daf，当前工作树未提交；未部署、未签发真实凭据、未操作真实业务数据。
- Python：复用 src/backend/.venv/bin/python，实际3.14.0。未发现可用3.11环境；uv读取用户缓存被沙箱拒绝后未绕过。所有Python3.14结果不等同于项目3.11基线验收。

## 已执行证据

| ID | 命令/范围（cwd src/backend） | 结果 |
|---|---|---|
| E-001 | `.venv/bin/python -m pytest test/open_api/test_kunlian_credential.py -q --tb=short` | 初始2 failed，服务缺失；子代理扩充先红后绿，最终凭据12例及相邻10例22 passed。含SQLite真实仓储CAS/轮换回滚与worker引用重验。 |
| E-002 | `.venv/bin/python -m pytest test/sso/test_kunlian_api_identity.py test/sso/test_kunlian_login_contract.py test/sso/test_kunlian_admission.py -q` | 初始身份26例预期缺失失败；修复映射/长度拒绝后63 passed（30新身份+33旧回归）。 |
| E-003 | `.venv/bin/python -m pytest test/open_api/test_kunlian_access.py test/open_api/test_kunlian_context_isolation.py test/open_api/test_kunlian_revalidation.py test/open_api/test_kunlian_error_contract.py -q --tb=short` | 6 passed。前置RED覆盖缺实现、继承管理tenant99覆盖7、映射换人、原Owner异常状态丢失。 |
| E-004 | `.venv/bin/python -m pytest test/open_api/test_kunlian_credential_routes.py test/open_api/test_kunlian_credential.py test/sso/test_kunlian_api_identity.py -q` | 44 passed。控制面cached超管两例RED→改fresh Owner后GREEN。 |
| E-005 | `.venv/bin/python -m pytest test/workflow/test_kunlian_permission_api.py` 及既有changes/reads/receipts | 21 passed（新2+旧19）。SQL持久回执实例重建、摘要冲突、F048 ledger待确认查回。非真实FGA。 |
| E-006 | `.venv/bin/python -m pytest test/workflow/test_kunlian_runtime.py test/workflow/test_kunlian_workflow_invocation.py test/workflow/test_kunlian_workflow_interaction.py test/workflow/test_kunlian_workflow_run_control_worker.py test/workflow/test_kunlian_workflow_run_control_cancel.py test/workflow/test_kunlian_workflow_publication.py -q` | 62 passed；含23正式运行用例。先RED三项缺接线，再RED核心图被拒，修复后真实LLMNode+GraphEngine直跑/交互恢复通过，仅外部模型与存储等边界替身。 |
| E-007 | `.venv/bin/python -m pytest test/workflow/test_kunlian_safe_responses.py test/workflow/test_kunlian_workflow_api.py -q` | 9 passed；列表图泄露、edit gate、SQL db_password和raw metadata图泄露先红后绿。 |
| E-008 | `.venv/bin/python -m pytest test/workflow/test_kunlian_management_concurrency.py test/workflow/test_kunlian_workflow_publication.py -q` | 7 passed；正式非mock草稿If-Match与迟到旧版本下线拒绝。SQLite非真实行锁证据。 |
| E-009 | `.venv/bin/python -m pytest test/open_api/test_kunlian_formal_http.py test/workflow/test_kunlian_workflow_api.py test/workflow/test_kunlian_safe_responses.py -q` | 16 passed；真实router/依赖，底层服务替身。先RED保存raw未封装、授权pending200、Owner冲突200，修复后GREEN。 |
| E-010 | `.venv/bin/python -m pytest test/open_api/test_kunlian_audit.py test/open_api/test_kunlian_credential.py -q --tb=short` | 14 passed；持久审计意图失败阻断，结果失败保留意图，SQL真实commit。 |
| E-011 | `.venv/bin/python -m pytest test/open_api/test_kunlian_http_audit.py test/open_api/test_kunlian_error_contract.py test/open_api/test_kunlian_dependencies.py -q --tb=short` | 5 passed；先RED只有business无intent，接入后intent→business→finish。 |
| E-012 | `.venv/bin/python -m pytest test/open_api/test_kunlian*.py test/sso/test_kunlian_api_identity.py test/workflow/test_kunlian_workflow_api.py test/workflow/test_kunlian_permission_api.py test/workflow/test_kunlian_runtime.py -q --tb=short` | 中间checkpoint66 passed；之后仍有代码新增，此结果不充作最终回归。 |

所有上述命令实际退出0（明确RED除外），依赖有17/18项既有warning，包含Python3.14 Pydantic v1兼容警告。子代理证据已向主线程交付；最终交付前需用同一工作树重跑联合选择。

## 已发现并修复的关键问题

- 超管管理资格使用正向缓存：改fresh User Owner资格核验。
- 身份异常错误码/HTTP丢失：保留Owner五位码及真实状态；WorkflowRegistrationError的409/403/503专用映射已修复，并有真实ASGI拒绝路径测试。
- 外层管理/bypass上下文继承：改tenant_execution_scope隔离并恢复。
- 版本列表/详情泄露编辑图：元数据白名单、edit gate及真实SQL凭据路径脱敏。
- 正式nonmock保存无If-Match、迟到v1下线v2：正式仓储Flow→Version锁及预期版本复核。
- 持久授权回执缺失：SQL绑定client-key摘要，未确认投影返回PENDING。

## 剩余工作与边界

- 正式路由、Key控制面及Worker模块已写入启动装配，但完整main生命周期/真实中间件外部依赖验收未执行。
- 新运行支持单文本表单输入、单文本输出，以及既有核心LLM/tool/code/condition/普通knowledge_retriever图拓扑。平台Agent与平台知识节点、多输入/多输出、附件/非文本协议仍在受理前拒绝；不宣称任意Workflow已支持。
- 人工输入持久恢复仅支持start直接进入输入节点，其后核心图可执行。
- 自动Beat有界补偿与过期正式终态清理已接；请求限流、可调时限、每用户跨工作流活跃运行上限已实现；真实Broker/Beat与双库锁竞争未验。平台受控处置及审计/授权PENDING人工核对说明见operations.md，不宣称自动修复。清理永久墓碑每轮仍有重复扫描成本。
- 授权receipt claim后、F048 ledger前崩溃可保持PENDING，需受控恢复，不可冒险重复写。
- 真实昆联、MySQL/DM8、OpenFGA、独立Broker/Worker进程、Python3.11均NOT_RUN。
- 本地阶段回归已完成，整体仍为PARTIAL：真实环境门禁未执行，不能声明可直接上线。

## 最终本地检查点（2026-11-16）

E-013：cwd `src/backend`，执行 `.venv/bin/python -m pytest test/open_api/test_kunlian*.py test/sso/test_kunlian_api_identity.py test/sso/test_kunlian_login_contract.py test/sso/test_kunlian_admission.py test/workflow/test_kunlian*.py test/open_api/test_credential_validator.py test/open_api/test_credential_service.py -q --tb=short`，**370 passed、2 skipped、18 warnings，exit 0**。两项跳过均为既有 `test_kunlian_workflow_run_control_e2e.py` 第114、167行：缺少本地redis-server（可用F126_REDIS_SERVER提供二进制），不是新增跳过以掩盖失败。额外 `pytest test/workflow/test_kunlian*.py -q -rs` 得240 passed、2 skipped、exit0确认该原因。Python3.14依赖警告仍存在。

E-014：全部modified/untracked Python定向Ruff检查通过；`git diff --check`、locales生成产物check、`check-i18n.mjs`通过。架构守卫未见VIOLATION；settings.py原有敏感默认项及secret roundtrip合成测试有RULE-7 WARNING，未加入真实秘密。

E-015：只读import正式`bisheng.main.app`成功，列出33条昆联相关路由（旧身份7、Key管理6、业务20）；没有执行lifespan，不替代真实服务验收。

E-016：资源/配额子批先RED后GREEN，默认活跃数5，User→UserTenant→Flow锁，跨workflow正式运行限额和幂等重放已测试；真实MySQL/DM8锁竞争NOT_RUN。清理子批14例GREEN，真实SQLite独立连接读取证明过期payload清除、关系归属与幂等墓碑保留、候选不变。

E-017：补充 `test/open_api/test_kunlian_real_key_http.py`，通过正式router与真实KunlianCredentialService签发/认证/撤销（仅仓储与外部身份端口隔离），证明允许租户200、越范围403且不解析用户、撤销后401且不执行业务。定向1 passed、exit0，Ruff通过。该证据不是真实昆联网络联调。

E-018：正式HTTP运行响应新增4项RED（任意失败文本外泄、取消缺cancel_state），修复后重跑E-013完整命令，**375 passed、2 skipped、18 warnings、exit0**；包含E-017真实Key生命周期HTTP组合。运行失败仅回允许的稳定分类，取消显式返回ACCEPTED/CONFIRMED/ALREADY_TERMINAL。当前最终代码测试证据以本条为准，早期计数为历史检查点。

E-019（T011，用户取消客户端请求键）：新增 `test/open_api/test_kunlian_no_client_key.py` 先运行6 failed（五接口缺Header422及OpenAPI仍声明必填），端点移除Header依赖、每次HTTP生成内部UUID后，定向与正式HTTP测试23 passed；相同旧Header连续请求得到不同内部操作引用。重跑E-013完整命令，**381 passed、2 skipped、18 warnings、exit0**。未改内部Worker去重/状态机、If-Match、授权修订或候选接口合同。当前最终证据以E-019为准，E-018为历史检查点；测试仍为Python3.14，不代表真实环境。

E-020（T012，公开身份改为user_account）：先观察User账号端口缺失RED1 failed、credential caller-only端口缺失RED1 failed、迁移HTTP套件RED32 failed/10 passed（旧Query合同/构造依赖）。实现仅账号Query后，账号仓储真实SQLite NOCASE/唯一成员与绑定隔离及相邻User/SSO测试60 passed；公开Key/HTTP/账号定向104 passed。最终执行 `.venv/bin/python -m pytest test/open_api/test_kunlian*.py test/user/test_kunlian_account.py test/user/test_kunlian_external_identity.py test/sso/test_kunlian_api_identity.py test/sso/test_kunlian_login_contract.py test/sso/test_kunlian_admission.py test/workflow/test_kunlian*.py test/open_api/test_credential_validator.py test/open_api/test_credential_service.py -q --tb=short`，**424 passed、2 skipped、18 warnings、exit0**。旧Queryonly/mixed拒绝，OpenAPI仅账号，先Key再账号再范围再身份；账号payload与反查事实不一致拒绝。内部RunSubject、授权subject_ref、审计外部标识保留，Worker/权限回归未改为相信请求账号。Ruff、架构守卫与diff-check通过。Python3.14、真实双库/昆联验收仍NOT_RUN。最新联合证据以E-020为准。

E-021：只读import真实 `bisheng.main.app`，断言 `/api/v2/kunlian/` 前缀下20条业务路由均实际注册，逐条检查统一用户依赖的query_params恰为 `{user_account}`，PASS/exit0。未执行lifespan，不访问真实DB/权限业务。审查一度误报open_endpoints聚合未include导致404，经main独立同级注册及本条证据排除，不修改正确接线。

### 验收覆盖判定

| AC | 本地证据 | 最终环境状态 |
|---|---|---|
| AC-01～AC-06 | E-001～E-004、E-013；Key、租户、用户、管理员拒绝与上下文 | PARTIAL：真实目录/资格未验 |
| AC-07～AC-10 | E-007～E-009、E-013；管理、修订、发布/下线、图脱敏及秘密回写 | PARTIAL：真实权限与双库事务未验 |
| AC-11～AC-14 | E-006、E-013；冻结、核心LLM真实引擎、交互、取消、撤权边界 | PARTIAL：独立Broker/Worker与未支持协议未验 |
| AC-15、AC-16 | E-005、E-009、E-013；授权持久回执及投影状态 | PARTIAL：真实FGA及崩溃PENDING处置未验 |
| AC-17、AC-20 | E-004、E-010、E-011、E-013；fresh超管、审计白名单与意图失败拒绝 | PARTIAL：真实审计/告警未验 |
| AC-18 | E-001、E-013；旧凭据validator相邻回归、独立前缀 | PARTIAL：全main中间件与浏览器部署回归未验 |
| AC-19 | api-guide、operations、e2e-checklist已交付 | PARTIAL：真实昆联E2E NOT_RUN |
| AC-21、AC-22 | E-013；真实Key服务轮换后查询/取消，原Key撤销阻断恢复 | PARTIAL：真实环境及时效验收未验 |

未执行coverage：本项目无此特性固定阈值，使用独立风险/合同测试；不将mock结果作为真实环境证据。

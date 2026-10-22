# F081：任务及特性代码自审

- Status: `PASS_WITH_NOTES`
- Reviewed: `2026-10-22`
- Base: `feat/2.5.0-sg`，`9386346422bdf0f3320eaa6cacc3328b4a68232b`
- 范围：本地工作树 diff 及新增文件，不能用分支尚无提交的 `base...HEAD` 空 diff 替代审查。
- 按项目 task-review、code-review 与 security-review 执行自审；没有使用独立 agent，不称为独立评审。
- 复用 [verification.md](verification.md) E-003～E-007，不重复运行同状态已通过的定向测试。

## 1. 任务检查

共同检查 #1 分层、#2 命名、#3 序列化、#4 数据库、#5 前端、#6 信息泄漏：后端实现适用项均 PASS，前端 N/A；测试按项目检查命名与 AC 标注，文档按 V0 检查。MCP 使用已确认原生协议，旧清单 DAO/JWT/REST 包装要求由根 AGENTS 与 F081 覆盖；无数据库模型/迁移或 Worker 实现任务。

| Task | 类型及文件范围 | 文件/配对测试/依赖 | 结论 |
|---|---|---|---|
| T001 | 两个新身份/仓储测试文件 | 范围 PASS，覆盖 AC 标注 PASS，红灯 E-002 后绿灯 E-003 | PASS |
| T002 | identity.py | 范围 PASS，T001/T005 配对，T001 先行 | PASS |
| T003 | tenant Repository 接口/实现及空包 | 范围 PASS，T001 配对；无 SQL 方言依赖或 Service SQL | PASS |
| T004 | user_context_service/auth_service | 范围 PASS，T001 配对；拒绝/恢复/角色失败测试 | PASS |
| T005 | tools/server 测试 | 范围 PASS，覆盖 AC 标注 PASS，SDK 红灯后统一接入 | PASS |
| T006 | browse/search schema | 范围 PASS，T005 配对；StrictRequest 导入调整已记录 | PASS |
| T007 | content/ingestion schema | 范围 PASS，T005 配对；仅顶层请求改身份 | PASS |
| T008 | query_tools/tools | 范围 PASS，T005 配对；必填签名/原检索一致 | PASS |
| T009 | content_tools/write_tools | 范围 PASS，T005 配对；无领域参数残留 | PASS |
| T010 | factory/router | 范围 PASS，T001/T005/T012/T013 配对；受管理只读 session 和 SDK 拒绝审计 | PASS |
| T011 | tool_runtime/search_service | 范围 PASS，T005 配对；统一目标身份、预算及审计 | PASS |
| T012 | search_factory/main_integration 测试 | 范围 PASS，覆盖 AC 标注 PASS；真实 TCP 断连含身份/业务两个阶段 | PASS |
| T013 | knowledge_flow 测试 | 范围 PASS，覆盖 AC 由任务追溯；真实仓储/服务+受控 Owner/角色/基础设施 | PASS |
| T014 | 完整使用文档 | 范围 PASS；JSON/Python 及账号示例检查 | PASS |
| T015 | F070/F078 身份说明及 usage | 文档多文件例外已记录，无历史验证记录重写 | PASS_WITH_NOTES |
| T016 | 验证及自审交付 | 范围 PASS；无提交/部署，存量失败及人工项明确 | PASS_WITH_NOTES |

测试源码中的旧 F070/F078 AC 标注保留用于历史行为；新增 F081 用例及 tasks 追溯负责新身份验收。未将旧计数冒充本特性结果。

## 2. 六维度检查

| 维度 | 高 | 中 | 低 | 结果及依据 |
|---|---|---|---|---|
| 边界条件 | 0 | 0 | 0 | PASS：严格账号、精确候选、全部当前关系唯一后验状态；模式错误/超时不降级 |
| 权限与认证 | 0 | 0 | 0 | PASS：HTTP Token 校验保持；目标 UserPayload 正常构造；业务前关闭 bypass 并应用目标租户；现有 Owner/PermissionService 不改 |
| 并发安全 | 0 | 0 | 0 | PASS：原 principal 只读、每调用解析/session，无身份缓存；SDK task 恢复六 ContextVar 与审计标记；写入不确定语义不变 |
| 信息泄漏 | 0 | 0 | 0 | PASS：固定身份拒绝、安全异常；Token/账号/正文/签名不入日志或错误；无硬编码秘密；未知工具审计不记录任意输入名称 |
| 测试覆盖 | 0 | 0 | 1 | PASS_WITH_NOTES：本特性 120 项通过；相关 338 passed/1 既有失败，真实设施人工验收见 verification |
| 代码风格及架构 | 0 | 0 | 0 | PASS：Ruff/架构守卫通过；新 ORM 读取在 Repository、无 Service SQL/新 DAO、无迁移/依赖/共享 Owner 改动 |

## 3. 风险与交付边界

有权访问 MCP 的 Token 可代理任意唯一有效账号，包括管理员并允许跨租户，这是用户确认的设计；必须由可信后端绑定真实登录身份。必填账号使旧调用方必须升级。回退应用代码不会撤销已创建业务数据。

本轮未修改共享 DeveloperToken、REST 身份代理、知识 Owner、PermissionService、Worker、依赖或配置。真实 FGA、队列、存储、数据库及部署仍待人工验收。总体为本地实现通过并附上述说明，不宣称生产或全量回归全绿。

# F112 实施任务

用户于 2026-10-22 确认按规格实施并运行相关验证；同范围连续实现、修复和复验已授权。

| 文档 | 状态 |
|---|---|
| spec.md | ✅ 已评审并获用户确认 |
| tasks.md | ✅ 已拆解；任务审查无阻塞问题 |
| verification.md | 已记录本地测试与真实服务限制 |

## 执行计划

以下后端任务按共同证据分批执行；测试任务不混入业务实现。路径相对仓库根目录。

- [x] T001 基础设施：登记 10973/10974 并定义共享不可用/未就绪领域错误。
  - 文件：`features/v2.6.0/release-contract.md`、`src/backend/bisheng/common/errcode/knowledge.py`。
  - 两个异常继承 BaseErrorCode，分别声明 http_status=503/409；不携带底层签名或正文。
  - _Requirements: REQ-006_ _Acceptance: AC-09_ _Verification: V-02_ _Depends: none_
- [x] T002 后端 Domain 测试：建立共享正文回退与 SPACE 拒绝的最小失败复现。
  - 文件：`src/backend/test/open_endpoints/test_filelib_shared_content.py`。
  - 文本缺失时执行实际共享仓储查询；其他版本/投影/无权/后端异常不得返回空成功，旧适配器调用即失败。
  - 覆盖 AC: AC-02, AC-03, AC-04, AC-09, AC-10
  - _Requirements: REQ-001, REQ-002, REQ-006, REQ-007_ _Verification: V-02_ _Depends: T001_
- [x] T003 后端 Domain：实现 Filelib 共享仓储接口和实现。
  - 文件：`src/backend/bisheng/knowledge/domain/repositories/interfaces/filelib_space_repository.py`、`src/backend/bisheng/knowledge/domain/repositories/implementations/filelib_space_repository_impl.py`。
  - 复用 KnowledgeMcpRepository 的共享 chunk 查询；补编码查询、主版本标记、批量摘要与清空根节点查询。SQL 仅在仓储内，遵守 MySQL/DM8 方言和租户事件。
  - _Requirements: REQ-001, REQ-002, REQ-004_ _Acceptance: AC-02, AC-03, AC-04, AC-07_ _Verification: V-02, V-04_ _Depends: T002_
- [x] T004 后端 Domain：实现共享内容服务与查询服务。
  - 文件：`src/backend/bisheng/open_endpoints/domain/services/filelib_space_content_service.py`、`src/backend/bisheng/open_endpoints/domain/services/filelib_space_query_service.py`。
  - require_space(s)、入口 resolver、实际内容文件、完整分块顺序与读取前后版本检查；列表不访问旧摘要函数。
  - _Requirements: REQ-001, REQ-002, REQ-006, REQ-007_ _Acceptance: AC-02, AC-03, AC-04, AC-09, AC-10, AC-11_ _Verification: V-02_ _Depends: T003_
- [x] T005 后端 Domain 测试：命令与共享生命周期的允许/拒绝路径。
  - 文件：`src/backend/test/open_endpoints/test_filelib_shared_commands.py`。
  - 三种入库均先检查资格/路由；创建绑定目标；批量跨空间拒绝；清空保留容器且不 drop 目标；失败不可标成功。
  - 覆盖 AC: AC-01, AC-02, AC-05, AC-06, AC-07, AC-09, AC-10
  - _Requirements: REQ-001, REQ-003, REQ-004, REQ-006, REQ-007_ _Verification: V-03, V-04_ _Depends: T001_
- [x] T006 后端 Domain：实现 Filelib 共享命令服务和专用创建 DTO。
  - 文件：`src/backend/bisheng/open_endpoints/domain/services/filelib_space_command_service.py`、`src/backend/bisheng/open_endpoints/domain/schemas/filelib.py`。
  - 创建默认团队库，物理参数须匹配路由；复用空间编辑/上传/删除/退役；字符串切片调用共享直写并记录真实状态；清空单次委托领域批量生命周期，不直接删原对象。
  - _Requirements: REQ-001, REQ-003, REQ-004, REQ-006, REQ-007_ _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-07, AC-09, AC-10_ _Verification: V-03, V-04_ _Depends: T005, T004_
- [x] T007 后端 Domain：补现有服务的必要共享适配入口。
  - 文件：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`、`src/backend/bisheng/open_endpoints/domain/services/filelib_file_source_service.py`。
  - 文件列表可显式关闭旧摘要加载，默认保持其他调用方行为；原地址仅接受 SPACE，保留原签名权限与身份规则。
  - _Requirements: REQ-001, REQ-002, REQ-005, REQ-008_ _Acceptance: AC-02, AC-04, AC-08, AC-11, AC-12_ _Verification: V-01, V-02, V-05_ _Depends: T004_
- [x] T008 后端 API 测试：14 条文件接口接线与排除边界。
  - 文件：`src/backend/test/open_endpoints/test_filelib_shared_api.py`、`src/backend/test/knowledge/test_knowledge_space_chat_service_retrieve.py`。
  - 默认类型、别名、成功响应和原链接/检索范围；QA/统计路由与函数 AST 对照；替换过时的旧函数模拟测试，保留独立业务断言。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-08, AC-10, AC-11, AC-12
  - _Requirements: REQ-001, REQ-002, REQ-005, REQ-007, REQ-008_ _Verification: V-01, V-05_ _Depends: T004, T006, T007_
- [x] T009 后端 API：依赖装配与 14 个文件接口收口。
  - 文件：`src/backend/bisheng/open_endpoints/api/dependencies.py`、`src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`。
  - 使用现有 session/业务用户上下文装配 resolver、退役和分发服务；写接口保留 default_operator；检索 SPACE 校验须在 external_id 上下文内执行；QA/统计函数保持。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_ _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_ _Verification: V-01 至 V-05_ _Depends: T008_
- [x] T010 后端 Domain 测试：真实 ORM 及共享仓储过滤契约。
  - 文件：`src/backend/test/open_endpoints/test_filelib_shared_repository.py`。
  - 使用 SQLite 与既有 tenant fixtures，实际执行编码/版本/根节点查询；ES fake 记录物理目标和 canonical 过滤，验证摘要不混版本。
  - 覆盖 AC: AC-02, AC-03, AC-04, AC-07, AC-10
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-007_ _Verification: V-02, V-04_ _Depends: T002_
- [x] T011 后端 API 测试：受控端到端闭环。
  - 文件：`src/backend/test/open_endpoints/test_filelib_shared_e2e.py`。
  - 通过 HTTP 请求覆盖入库、列表、详情、检索、原地址、删除/清空；外部系统可控替身，业务服务和共享读取不得全链模拟；沿用既有 writer/lifecycle 回归证明幂等和引用保留。
  - 覆盖 AC: AC-03, AC-05, AC-06, AC-07, AC-08, AC-11
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-008_ _Verification: V-06_ _Depends: T009, T010_
- [x] T012 文档与验证：更新 Filelib 接口说明及结果证据。
  - 文件：`docs/api/filelib-openapi-interfaces.md`、本目录 `verification.md`。
  - 记录默认值、非 SPACE 拒绝、团队库、错误与切片语义；执行相关回归、静态、架构和代码审查，记录实际命令、基线失败与真实服务/DM8 未验证项。
  - _Requirements: REQ-008_ _Acceptance: AC-01, AC-02, AC-09, AC-11, AC-12_ _Verification: V-01 至 V-06_ _Depends: T011_

## 实际偏差记录

- 沿用当前分支与工作区，不切换/提交：已有未提交 MCP 身份开发，F112 只操作声明范围；先保存既有文件哈希与排除接口 AST，完成时复核。
- 不创建新测试基础设施或 Worker；复用现有共享 writer、分发、回收与空间退役任务，租户上下文沿用其现有 Celery headers → ContextVar 链路。
- T010 对 T003 的仓储行为提供主要验证；执行时先编写该测试，再实现 T003，避免按编号误解为实现后补测试。

- 实际使用新增 FilelibSpaceRepository 接口/实现复用 KnowledgeMcpRepository 查询规则，未修改 MCP 仓储及 FilelibRetrieveService，避免影响已有调用。
- 检索复用已注入 file_repo 的 session，在 external_id 上下文内构造 SPACE 校验，不新增提前打开数据库的依赖，保留无效身份输入的拒绝顺序。
- 补充 `test_filelib_external_user_context.py`、`test_filelib_knowledge_list.py`、`test_filelib_file_source_url.py` 三份既有契约用例（T013），仅更新新范围预期并增加原链接拒绝路径。
- 详情最终以独立 managed session 复核内容身份，避免 MySQL REPEATABLE READ 隐藏并发主版本/代次变化；字符串写入最终状态刷新并锁定文件，保留 writer 已提交代次和生命周期。
- 项目旧 E2E 模板面向外部已部署环境；本次依确认规格使用 SQLite + 可控 ES/MinIO/writer 边界的受控 HTTP E2E，不新建外部认证/清理基础设施。真实 Worker、OpenFGA、MySQL/DM8、ES/Milvus/MinIO 单列人工验证。
- 相关 shared-only 回归有一项既有夹具缺少 document_id 的失败；用 HEAD 版本的六个受影响既有模块重新加载后，同一用例仍失败。未修复无关回收测试。

### T013 后端 API 测试：既有 Filelib 契约适配

- [x] 范围：`test/open_endpoints/test_filelib_external_user_context.py`、`test_filelib_knowledge_list.py`、`test_filelib_file_source_url.py`（均位于 src/backend）。
- 保留 external_id 资格/作用域与错误优先级；列表默认 SPACE，非 SPACE 拒绝；原地址覆盖回收、跨租户、旧类型拒绝。
- 覆盖 AC: AC-01, AC-02, AC-08, AC-10, AC-11, AC-12
- _Requirements: REQ-001, REQ-005, REQ-007, REQ-008_ _Verification: V-01, V-05_ _Depends: T009_

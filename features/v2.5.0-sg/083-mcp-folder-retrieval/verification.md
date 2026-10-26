# F083：实施与验证证据

- Feature ID: `083-mcp-folder-retrieval`
- Status: `LOCAL_VERIFIED_MANUAL_REQUIRED`
- Verified: `2026-10-26`
- Branch: `codex/mcp-folder-retrieval`
- Base: `a0c0b538cf95a7cacc3e5a6f8f481f4575e1ac8a`（`feat/2.5.0-sg`）
- Code state: 本分支未提交工作区；最终回归后无行为代码变化，仅增加保留中文提示的 Ruff 注解和交付文档。
- Runtime: `src/backend/.venv/bin/python`，Python 3.10.19，Pydantic 2.12.4；未安装或升级依赖。

## 1. 交付结果

新增 retrieve_folder_chunks，完整参数、单空间单目录、默认递归/false 当前层、folder_id 字符串兼容、目标 external_id 身份、逐文件权限、1000 候选预算和 30 秒只读总预算均接入。

目录范围在召回前进入共享检索，启用 resolver 的 strict_explicit，并在来源签发前检查返回入口范围。空目录不进入检索；超限整次拒绝；旧工具默认参数/行为和 REST schema 未扩展。使用文档已补充示例、限制和错误处理。

本轮未提交、合并、推送、部署、修改运行配置或真实业务/权限数据。

## 2. 可复用证据

以下 pytest 命令均在 `src/backend/` 下用 `.venv/bin/python -m pytest` 执行，均带 `-q --disable-warnings --tb=short`。日志位于本机 `/tmp`，不包含真实凭证。

| Evidence | Command / Step | Result | Scope |
|---|---|---|---|
| E-001 | `test/mcp_server/test_mcp_tools.py test/open_endpoints/test_filelib_retrieve_service.py test/knowledge/test_mcp_knowledge_repository.py test/knowledge/test_knowledge_space_chat_service_retrieve.py`，修改前基线 | PASS：99 passed，7.63 秒；`/tmp/f083-baseline.log` | 旧协议、目录仓储和共享检索基线 |
| E-002-RED | 新范围服务/仓储测试先行 | 预期红灯：8 failed、3 passed；缺失新服务导致 ModuleNotFoundError；`/tmp/f083-scope-red.log` | T002 先行证据，不代表功能通过 |
| E-002 | `test/knowledge/test_mcp_folder_retrieval_service.py test/knowledge/test_mcp_knowledge_repository.py` | PASS：11 passed，2.36 秒；`/tmp/f083-scope-green.log` | 路径边界、多批完整性、0/101/1000/1001、权限拒绝/异常及无进展 |
| E-003-RED | 新内部范围/严格检索边界测试先行 | 预期红灯：12 failed、2 passed；内部参数不存在；`/tmp/f083-retrieve-red.log` | T004 先行证据 |
| E-003 | `test/open_endpoints/test_filelib_retrieve_service.py test/knowledge/test_knowledge_space_chat_service_retrieve.py` | PASS：64 passed，3.52 秒；`/tmp/f083-retrieve-green.log` | None/空/非空、过滤交集透传、越界来源守卫、严格映射和旧默认 |
| E-004-RED | SDK 新工具主路径、容量拒绝及实际装配流程先行 | 预期红灯：新工具未注册/工厂无此操作；`/tmp/f083-sdk-red.log`、`/tmp/f083-flow-red.log` | T006/T008 先行证据；无效参数用例的早期未知工具拒绝不单独作为 schema 通过证据 |
| E-004 | 最终相关回归，完整命令见下 | PASS：383 passed，94 warnings，21.91 秒；`/tmp/f083-final.log` | SDK、真实仓储、受控端到端、目标账号、Token、范围解析、共享检索、来源和权限 |
| E-005 | `test/open_endpoints/test_filelib_external_user_context.py` | PASS：17 passed，6 warnings，2.79 秒；`/tmp/f083-rest.log` | REST 账号代理兼容；与 E-004 合计 400 项通过 |
| E-006 | Ruff：新增/主要修改的十个文件全文件检查；其余五文件对照 HEAD | PASS：主要文件无问题；共享文件原有 26 条诊断，本次仍 26 条，无新增 | 不是整个仓库 Ruff 零诊断；范围格式化避免无关旧代码重排 |
| E-007 | `bash scripts/arch-guard.sh`，参数为所有修改 Python 文件及两个新增 Python 文件 | PASS，exit 0，无输出 | DDD、数据库兼容禁用项及信息泄漏规则 |
| E-008 | Node 检查 Markdown 引用、JSON 示例、REQ/AC/设计/任务映射；`git diff --check`、最终范围检查 | PASS | 使用文档、规格和交付证据结构；暂存区无修改 |

最终相关回归命令：

```bash
.venv/bin/python -m pytest \
  test/mcp_server \
  test/developer_token/test_developer_token_service.py \
  test/developer_token/test_developer_token_repository.py \
  test/developer_token/test_developer_token_dependency.py \
  test/developer_token/test_developer_token_api.py \
  test/knowledge/test_mcp_folder_retrieval_service.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/knowledge/test_knowledge_retrieval_scope_resolver.py \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  -q --disable-warnings --tb=short
```

SDK 批次中曾有一处测试仍将审计条数固定为 10，新增第十一个工具后实际为 11；已改为与参数表长度对应，保持每次拒绝必须有且只有一条审计的约束。最终 E-004 已覆盖修正后的用例。

## 3. AC coverage matrix

| Acceptance | Status | Evidence | 证据边界 |
|---|---|---|---|
| AC-01 | PASS | E-004 | 真实 SDK 十一工具、必填身份、严格参数、兼容集合和结果 |
| AC-02 | PASS | E-002、E-004 | 实际 SQLite 路径查询与 SDK 递归/false 业务流程，非真实数据库部署验收 |
| AC-03 | PASS | E-002、E-003、E-004 | 完整多批、空集短路、恰好 1000/1001 和安全容量提示 |
| AC-04 | PASS | E-002、E-004 | 目标用户/租户、目录拒绝、文件 ACL 拒绝和权限异常；外部权限服务受控 |
| AC-05 | PASS | E-003、E-004 | file_ids/标签交集、strict_explicit 实参、resolver 既有严格映射及来源签发前守卫 |
| AC-06 | PASS | E-002、E-003、E-004 | 空结果、主链路失败、身份超时/既有运行时清理和来源超时兼容 |
| AC-07 | PASS | E-004、E-005、E-006、E-007、E-008 | 本地接口回归、文档、架构及增量 lint；不代表已上线 |

## 4. 端到端与未执行项

E-004 中的 `test_nine_tools_sdk_flow_uses_real_services_and_repositories` 已扩展文件夹检索，保留原函数名兼容定位。它使用真实 MCP SDK、真实目标身份解析/ORM、实际目录仓储、factory、runtime 和 FilelibRetrieveService；权限 Owner、对象存储、任务及检索后端为受控端口。

该流程证明默认递归只返回 901/902，当前层只返回 901，无权文件 903 和相似目录 3050 内文件 904 不进入检索；合法空目录 401 不调用检索。Token 绑定用户与目标用户不同，且其他租户及无权目标账号的调用被拒绝。流程结束后受管理会话与暂存对象清理。

| Verification | Status | 原因 / 后续步骤 |
|---|---|---|
| 实际 MySQL / DM8 | MANUAL_REQUIRED | 当前范围测试使用 SQLite；在 CI/Linux 使用两种实际驱动复核路径分页、1000 候选及 canonical 参数规模，macOS 无 DM8 驱动 |
| 实际 OpenFGA / MinIO / Milvus / ES | MANUAL_REQUIRED | 本轮没有连接真实服务；在受控测试环境准备目录/子目录/无权入口，核对召回和来源地址 |
| 大目录时延和资源占用 | MANUAL_REQUIRED | 1000 预算是保护阈值；真实目录分布、权限和数据库延迟未测，不承诺 30 秒必成 |
| 可信后端账号绑定 | MANUAL_REQUIRED | MCP 不证明账号字符串属于调用者；接入方需要从登录会话覆盖 external_id |
| 已部署服务验证 | NOT_RUN | 本次未要求部署或使用远端 Token；上线后刷新 tools/list，再验证新工具 |

未运行无关全量测试；无迁移、配置、前端或 Worker 变更。目录移动/权限变化不提供跨数据库、权限服务和索引的原子快照，下一调用重新解析，最终授权保持既有规则。

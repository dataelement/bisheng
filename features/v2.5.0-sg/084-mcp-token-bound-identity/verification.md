# F084：验证记录

- Status: `LOCAL_VERIFIED_MANUAL_REQUIRED`
- Verified: `2026-11-02`
- Branch: `codex/mcp-token-bound-identity`
- Base: `3d82e3ff9a65f473afeb73c9806b6c9387ed5329`（feat/2.5.0-sg）
- Code State: 当前未提交工作区；最终回归后仅更新测试说明文字和交付文档，无行为变化。
- Runtime: `src/backend/.venv/bin/python`，Python 3.10.19；没有安装/升级依赖。

## 已实现

十工具签名、公共请求 schema 和 DTO 构造均不含 external_id；显式传入被拒绝，不提供兼容代理。身份服务只读取已认证 principal.user/tenant_id，保留绑定角色，不查询账号/当前租户、默认租户或重新加载登录身份。两执行链路保持原上下文、超时和审计，绑定权限进入既有领域服务。

仅修改 MCP、相关测试与文档；DeveloperTokenService、REST、共享仓储、细粒度权限、Worker、存储和运行配置未改。本轮不提交、合并、推送或部署，不迁移历史文件。

## Evidence

命令除另有说明外，在 src/backend 下使用 `.venv/bin/python -m pytest`，附 `-q --disable-warnings --tb=short`。

| Evidence | Command / Step | Result | Scope |
|---|---|---|---|
| E-001 | 修改前 `test/mcp_server` | PASS：119 passed，21.79 秒；`/tmp/f084-baseline.log` | 代理模型修改前基线，不作为新功能验收 |
| E-002 | T001 的绑定身份与移除字段回归先行 | 预期 FAIL：3 failed、4 passed；旧构造需仓储/账号，旧模型接受账号，SDK 暴露账号；`/tmp/f084-red.log` | 先行失败原因与回退目标一致 |
| E-003 | `test/mcp_server` 模块 | PASS：103 passed，14.89 秒；`/tmp/f084-mcp-green.log` | SDK、HTTP、身份、并发、取消、端到端与工厂 |
| E-004 | 最终相关回归，完整命令见下 | PASS：346 passed，81 warnings，17.58 秒；`/tmp/f084-final.log` | MCP、Token、REST 代理、知识权限/内容/上传、检索及来源兼容 |
| E-005 | `.venv/bin/python -m ruff check bisheng/mcp_server test/mcp_server` | PASS：All checks passed | 整个 MCP 实现和测试目录，无新增 lint 例外 |
| E-006 | 根目录 `bash scripts/arch-guard.sh`，参数为所有修改 Python 文件；`git diff --check` | PASS，exit 0 | 分层、信息泄漏与差异空白 |
| E-007 | 解析使用文档全部 JSON/Python 示例，扫描 MCP 生产源码 | PASS：19 个 JSON、1 个 Python 示例；MCP 生产源码 external_id 引用数为 0 | 示例不再传账号，不依赖 BISHENG_EXTERNAL_ID；源码 AST 可解析 |

早期整模块验证发现两类测试装配未同步：TCP 取消测试仍调用双参数身份回调，真实 Token 测试仍预期目标租户 7（实际绑定租户为 5）。已分别更新为一参数回调和绑定租户断言；权限及会话清理断言未弱化，E-003/E-004 均覆盖修正后的场景。

最终回归命令：

```bash
.venv/bin/python -m pytest \
  test/mcp_server \
  test/developer_token/test_developer_token_service.py \
  test/developer_token/test_developer_token_repository.py \
  test/developer_token/test_developer_token_dependency.py \
  test/developer_token/test_developer_token_api.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/knowledge/test_knowledge_retrieval_scope_resolver.py \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  -q --disable-warnings --tb=short
```

## AC Coverage

| Acceptance | Status | Evidence | 具体证据 |
|---|---|---|---|
| AC-01 | PASS | E-003、E-004、E-007 | 十工具无账号 schema、每工具显式账号字段拒绝、无账号参数的 SDK 调用成功 |
| AC-02 | PASS_LOCAL | E-003、E-004 | 绑定 UserPayload 保持原角色/引用，使用 Token 归属租户；身份阶段无 DB 会话；无权/跨租户拒绝；真实 SQLite 文件操作者与入队上下文一致 |
| AC-03 | PASS_LOCAL | E-003、E-004 | Token 实际规则及失败状态、六 ContextVar 恢复、并发 Token 隔离、真实 TCP 断连取消、审计脱敏 |
| AC-04 | PASS_LOCAL | E-004 | REST external_id 代理保持，folder_id 字符串、预览/来源、上传大小和既有权限测试通过 |
| AC-05 | PASS | E-005、E-006、E-007 | 使用文档/SDK 示例移除账号配置、说明 Token 绑定权限及客户端刷新要求 |

测试数从旧 MCP 基线 119 变为 103，是将跨账号/多当前租户选择的代理专属场景替换为绑定身份场景；不再保留不属于新契约的代理断言。HTTP Token 失败、并发/取消、未知参数、业务权限与写入回查继续覆盖。

## 真实设施及上线边界

端到端测试使用真实 SDK、实际工厂/领域服务和 SQLite，OpenFGA/MinIO/检索/队列端口受控；不能声称真实设施或生产验收通过。

| 验证项 | Status | 后续方式 |
|---|---|---|
| 实际 MySQL/DM8、OpenFGA、MinIO、Milvus/ES、Worker | MANUAL_REQUIRED | 在部署测试环境准备两枚不同绑定用户/租户 Token，验证资源允许/拒绝、预览和两种写入回查；本次无新数据库查询或迁移 |
| 部署代理和现有 MCP 客户端升级 | NOT_RUN | 本次未部署，发布后刷新 tools/list 并去掉 external_id，再执行受控读写验证 |
| 无关全量测试 | NOT_RUN | 未改变无关模块，仅运行相关回归；不以此声称全仓库测试通过 |

回退不会更改历史文件的用户或租户归属。需要恢复账号代理模式时可回退本次代码；此行为需重新按权限变更处理。

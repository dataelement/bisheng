# F081：验证证据

- Status: `LOCAL_VERIFIED_WITH_BASELINE_FAILURE`
- Updated: `2026-10-22`
- Branch: `codex/mcp-external-user-identity`
- Base: `9386346422bdf0f3320eaa6cacc3328b4a68232b`（feat/2.5.0-sg）
- Python: `src/backend/.venv/bin/python`，3.10.19；无新增依赖。
- 最终 Python 工作树指纹：`78c677b993e80b4508499380e5684328d15968270896b7a5c3063bf9e01aa87e`。对新增及修改 Python 文件按路径排序，将路径和文件字节依次 SHA-256；27 个文件，包含空包文件。不以文档修改让同状态行为证据失效。
- 未提交、未合并、未推送、未部署，未执行真实远程业务写入。

## 1. 实际执行记录

以下 pytest/Ruff 命令 cwd 为 `src/backend/`，其余 cwd 为仓库根目录。

| Evidence | 命令 / 实际步骤 | 结果 | 范围 |
|---|---|---|---|
| E-001 | `.venv/bin/python -m pytest test/mcp_server -q --tb=short`，改动前 HEAD | PASS：80 passed，14.38 秒 | 原 MCP 基线，不能替代新契约 |
| E-002 | 新身份服务/仓储测试先行，以及十工具必填 schema SDK 测试先行 | 预期失败：新模块缺失导致 2 个 collection error；SDK schema 缺 external_id 断言失败 | 身份与协议红灯；中间错误非最终验收 |
| E-003 | `.venv/bin/python -m pytest test/mcp_server test/tenant/test_tenant_membership_repository.py -q --tb=short` | PASS：120 passed，15.39 秒，exit 0 | 最终 MCP/身份/真实仓储/SDK/TCP/E2E；日志 `/tmp/f081-mcp-final.log` |
| E-004 | 下方最终相关回归命令 | 338 passed、1 failed，20.37 秒，exit 1 | MCP、Token、REST 代理/检索/来源、用户仓储、知识权限/上传；日志 `/tmp/f081-regression-final.log` |
| E-005 | 干净 HEAD 导出到临时目录，复用同一虚拟环境，独立执行下方部门上传测试；当前工作树同命令对照 | 两者均 1 failed，失败节点及根因一致 | 原有测试设施缺口；日志 `/tmp/f081-head-baseline.log`、`/tmp/f081-current-department.log` |
| E-006 | `.venv/bin/python -m ruff check bisheng/mcp_server bisheng/tenant/domain/repositories test/mcp_server test/tenant/test_tenant_membership_repository.py`；同范围 Ruff format/check；架构守卫检查新增/修改 Python 文件；`git diff --check` | PASS | 风格、分层、禁用方言写法、空白及范围 |
| E-007 | 文档检查脚本：解析 JSON、编译 Python 示例、检查引用、REQ/AC 与任务依赖及文件范围 | PASS：接入文档 27 段 JSON、15 个带账号调用、3 段 Python；16 任务无悬空/逆序依赖 | V0；F081 自审与文档内容按当前状态核对 |

最终相关回归命令：

```bash
.venv/bin/python -m pytest \
  test/mcp_server \
  test/tenant/test_tenant_membership_repository.py \
  test/developer_token \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/user/test_user_repository_external_id.py \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_department_knowledge_space_upload_permission.py \
  -q --tb=short
```

基线对照命令：

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_department_knowledge_space_upload_permission.py \
  -q --tb=short
```

不是将当前文件临时覆盖回 HEAD：通过 `git archive HEAD src/backend` 导出隔离源代码，独立 cwd/PYTHONPATH，仍使用同一虚拟环境。临时源代码已自动清理，原工作树未改。

## 2. 存量失败

失败节点：`test_department_space_upload_does_not_create_approval_request`。

链路为既有 `KnowledgeSpaceService.add_file` → `_require_not_write_frozen` → `KnowledgeSpaceSharedStorageRoutingDao.aget_by_tenant` → 测试桩配置下创建数据库连接；SQLAlchemy URL 解析报 `ValueError: not enough values to unpack (expected 3, got 0)`。干净 HEAD 与当前工作树均复现，未经过新增 MCP 身份链路。未修改知识上传 Owner 或扩大本特性范围修复该测试设施；相关回归不能表述为全绿。

## 3. AC 覆盖与证据边界

| AC | 本地状态 | 主要证据与可观察结果 |
|---|---|---|
| AC-01 | PASS | E-003/E-004：十 schema 必填、十缺参拒绝、非法字符串 SDK 拒绝，握手/列工具无需账号；输出与 FolderScope 没有新增身份字段 |
| AC-02 | PASS | E-004：真实 Token 校验及 HTTP 401/403/429/503、空/非空路由规则，拒绝不进入工具；Token 共享实现无改动 |
| AC-03 | PASS | E-003/E-004：严格规范化、前导零、唯一候选/禁用/不存在/不精确候选/重复拒绝，无角色或 Token 回退 |
| AC-04 | PASS（受控权限端口） | E-003：Token 8/目标 7 可读取和写入目标租户 7；Token 7/目标 9 在同租户无权时读写拒绝；工厂收到目标角色，不从 Token 借权 |
| AC-05 | PASS（SQLite/受控角色） | E-003：真实 Tenant/UserTenant Repository 查询，当前关系不先筛状态、不 inner join 丢失记录；多/零当前关系及停用租户拒绝；Token 与目标不同租户成功 |
| AC-06 | PASS（本地） | E-003：单租户跳过成员选择，仍校验默认租户，模式异常拒绝；解析没有注册、同步或补建身份数据路径 |
| AC-07 | PASS（受控 Owner/存储/任务） | E-003：生产身份解析+原 UserRepository 查询+真实 tenant/知识仓储和九工具服务；十名称实调；两个写工具受理后独立 session 核对 user_id/tenant_id，回查正文及投递操作者；领域参数无 external_id |
| AC-08 | PASS（本地 SDK/TCP） | E-003：同 Token 不同账号并发、继承污染上下文、角色异常、模式异常、身份超时、身份/业务阶段真实 TCP 断连；scope/session/ContextVar 释放 |
| AC-09 | PASS | E-003：SDK 参数拒绝也有一次接入审计，目标为空；已解析调用区分 Token/目标用户及租户；异常、账号/签名/正文不回显，日志只留必要 ID 和安全原因 |
| AC-10 | PASS（本地回归；存量失败另列） | E-004/E-006/E-007：REST 代理/检索/来源、folder_id、CORS、Token 语义回归；使用文档示例及旧客户端升级、可信后端责任、回退边界已同步 |

## 4. 端到端与人工验收

按项目 e2e-test 流程，复用 `test/mcp_server/test_mcp_knowledge_flow.py` 和 `test_main_integration.py`，不另建 REST/JWT harness：本入口是 MCP 原生协议、开发者 Token，非 REST 包装。SQLite 数据库为每测试新建；新账号/租户/文件使用 e2e-mcp 前缀或专用测试表，不连接正式库，不做远程清理。

真实 SDK/ASGI/TCP、生产身份服务/工厂、UserRepository 查询、Tenant/UserTenant/知识仓储及 MCP 领域服务在本地实际执行。全局 User import 预桩存在，因此 UserRepository 的模型换为真实 SQLModel 测试表；角色加载、Owner/FGA、存储、检索基础设施和 Worker 投递仍是受控端口。不能将这些结果解释为真实 MySQL/DM8、OpenFGA、MinIO 或 Worker 通过。

以下均为 `MANUAL_REQUIRED`，本轮未部署或操作真实服务：

1. 可信业务后端：从真实会话固定/覆盖账号；终端或模型尝试替换账号时无法改变该值；Token 不交给不可信客户端。
2. MySQL 及 Linux/CI DM8：精确账号候选、实际当前关系、启用租户及目标角色加载；macOS 没有 DM8 驱动。
3. 实际 FGA 与各类知识空间：Token A/目标 B 双向允许/拒绝、同租户无权与跨租户资源拒绝；管理员目标按正常权限入口生效。
4. 真实存储/队列：受控测试空间执行两个写工具，核对创建者/Owner/授权补偿、配额、存储前缀、Celery tenant headers 及 Worker 解析后回查；需另行授权真实写入。
5. 代理部署：工具列表刷新、必填账号、实际预览/检索、请求体和超时；代码回退不删除已创建文件。

## 5. 实施审查中修正

- Python 3.10 的内置 TimeoutError 与 asyncio.TimeoutError 不同，AnyIO 身份超时先被普通异常分支吞为通用失败；新增 SDK 超时测试复现后，两执行链路同时捕获并保留明确超时结果。
- SDK 在函数执行前拒绝缺参/类型时，原业务 finally 不会运行。协议层补安全审计，task-local 标记避免业务调用重复记录，所有分支恢复标记；不记录原始工具参数。
- StrictRequest 保持无身份通用模型，定义移入 identity.py 并从 browse.py 保留原导入路径，避免响应或嵌套对象被增加必填账号和循环导入。

结论：本地实现与新增身份契约验证完成，无本特性新增失败；相关回归保留一项已对照的存量失败，真实设施与部署验收尚未执行。

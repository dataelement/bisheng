# MCP 九工具实施验证

最新目录 ID 字符串兼容证据见 §8；`get_file_source` 缺陷修复见 §7。§1～6 保留最初九工具实施记录。

- 日期：2026-10-16。
- 基线：`feat/2.5.0-sg-main` / `06bc21e27`。
- 工作分支：`codex/078-mcp-knowledge-tools`，改动尚未提交、合并、推送或部署。
- 状态：`IMPLEMENTED_LOCAL_WITH_BASELINE_FAILURES`。
- 任务与契约：[tasks.md](tasks.md)、[spec.md](spec.md)；调用说明：[usage.md](usage.md)。

## 1. 结论与证据边界

九工具及原 `search_knowledge` 已接入。最终相关回归 **308 passed、6 failed、110 warnings，20.50 秒**。六个失败在未修改的 HEAD 快照中全部复现，不能宣称整体回归全绿；本次实现涉及的 MCP/新知识服务 **73 项全部通过**。

使用 Python 3.10.19、项目 `.venv`，外部依赖不升级。测试覆盖真实 MCP SDK、ASGI 和已有主应用 TCP 路径、新领域服务、真实 SQLite ORM 查询及入口解析器；权限、对象存储、检索和队列在相应用例中采用受控外部端口。没有向真实业务环境写文件或数据。

真实 MySQL/DM8、OpenFGA、MinIO、Redis、ES/Milvus、Celery Worker、线上代理和生产资源未验收。下面的 `LOCAL_PASS` 指可重复执行的本地证据，不能等同于生产验收。

## 2. 可复用执行证据

所有命令默认在 `src/backend` 执行，Python 为 `.venv/bin/python`。

| 证据 | 命令或范围 | 观察结果 |
|---|---|---|
| E01 基线 | `python -m pytest test/mcp_server -q --tb=short`，实施前 | 37 passed，7.93 秒 |
| E02 测试先行 | 旧工具列表用例 + 新 `test_mcp_tools.py`，实施前 | 11 failed、1 passed；缺少九名称、运行边界和请求体属性 |
| E03 领域测试先行 | 新查询/仓储/正文/写入测试，领域模块创建前 | 缺失模块导致收集失败；仅作为缺失功能的红灯 |
| E04 缺陷回归 | 正文分块跨页分隔符、隐藏祖先下目录可写筛选 | 两用例先失败，修复后查询/内容批次 9 passed |
| E05 协议加严 | 新检索嵌套 filters 身份字段拒绝 | 先 2 failed；严格子模型后 2 passed、11 deselected |
| E06 schema 一致性 | `python -m pytest test/mcp_server/test_mcp_tools.py::test_new_tool_schemas_and_annotations -q --tb=short` | 先 1 failed；统一签名和请求模型的长度/数量别名后 1 passed，3.13 秒 |
| E07 SDK 流程 | `python -m pytest test/mcp_server/test_mcp_knowledge_flow.py -q --tb=short` | 1 passed，3.38 秒；全部九工具，含合法非空标签过滤、创建/上传/回查 |
| E08 canonical 边界 | `python -m pytest test/knowledge/test_mcp_knowledge_content_service.py::test_logical_entry_reads_current_physical_content_with_entry_scope -q --tb=short` | 1 passed，2.26 秒；授权入口的正文不暴露私有管理入口元数据 |
| E09 最终回归 | 下列完整命令；最后一次生产变更为不确定投递的安全审计日志 | 308 passed、6 个存量失败，20.50 秒 |
| E10 HEAD 对照 | 未修改 HEAD 快照，单独运行两个出现失败的旧测试文件 | 8 passed、同样 6 failed，3.55 秒；失败位置/原因相同 |
| E11 静态门禁 | 24 个变更 Python 文件的 Ruff 检查/格式；15 个生产文件逐一架构守卫；diff 和文档检查 | 见 §6 |
| E12 本功能最终模块验证 | `python -m pytest test/mcp_server test/knowledge/test_mcp_knowledge_query_service.py test/knowledge/test_mcp_knowledge_repository.py test/knowledge/test_mcp_knowledge_content_service.py test/knowledge/test_mcp_knowledge_ingestion_service.py -q --tb=short` | 73 passed、39 warnings，9.57 秒；同一代码状态亦包含于 E09 |
| E13 恢复审计回归 | 写入投递失败用例增加断连后可定位 ID 及错误文本脱敏断言 | 补日志前 1 failed；修复后 E12/E09 通过 |

最终回归命令：

```bash
.venv/bin/python -m pytest \
  test/mcp_server \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_file_source_url.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/knowledge/test_knowledge_document_entry_resolver.py \
  test/developer_token/test_developer_token_dependency.py \
  test/developer_token/test_developer_token_service.py \
  test/developer_token/test_file_sync_fine_grained_permissions.py \
  test/api_rate_limit/test_api_rate_limit_middleware.py \
  test/knowledge/test_upload_extensions.py \
  test/knowledge/test_upload_file_size.py \
  test/knowledge/test_knowledge_upload_domain_tags.py \
  test/knowledge/test_department_knowledge_space_upload_permission.py \
  test/knowledge/test_knowledge_parse_priority_dispatch.py \
  -q --tb=short
```

最终输出保存在 `/tmp/bisheng-mcp-final-regression-20261016.log`。HEAD 对照是通过 `git archive HEAD src/backend` 提取到专属临时目录，复用同一 Python 环境运行以下命令，不改当前工作区：

```bash
/Users/wenruli/code/project/bisheng/bisheng/src/backend/.venv/bin/python -m pytest \
  test/knowledge/test_knowledge_upload_domain_tags.py \
  test/knowledge/test_department_knowledge_space_upload_permission.py \
  -q --tb=short
```

对照输出：`/tmp/bisheng-mcp-baseline-20261016.log`。

## 3. 六个存量失败

| 原测试 | 当前与 HEAD 相同的失败 |
|---|---|
| `test_upload_process_rejects_invalid_business_domain_code` | 原模型未拒绝 `bad`，预期的 ValueError 未发生 |
| `test_space_file_create_req_rejects_invalid_business_domain_code` | 同上 |
| `test_business_domain_split_rule_helpers` | 原工具把 `bad` 归一为 `BAD`，测试预期 None |
| `test_sync_process_knowledge_file_applies_manual_upload_tags` | 测试提供的文件 tenant_id 为 None，已有流程执行 `int(None)` |
| `test_space_add_file_persists_upload_metadata` | 旧测试 patch 的 `_get_parse_knowledge_file_task` 已不存在 |
| `test_department_space_upload_does_not_create_approval_request` | 旧测试未隔离已有共享存储写冻结查询，测试数据库配置不可用 |

这两个旧文件及它们对应的既有生产实现均未修改。此次不扩大范围修复旧业务域语义或测试装配。上述失败依然存在。

## 4. 验收追溯

| AC | 本地状态与主要证据 | 仍需真实环境验证 |
|---|---|---|
| AC-01 | LOCAL_PASS：E09 的旧/新协议鉴权、Token/IP/限流回归 | 真实 Token 配置、限流服务 |
| AC-02 | LOCAL_PASS：E06/E09，十名称、注解、旧检索兼容 | 客户端实际发现 |
| AC-03 | LOCAL_PASS：查询服务可写筛选、根/目录独立授权、隐藏路径回归 | 实际部门/团队/个人权限模型和大目录耗时 |
| AC-04 | LOCAL_PASS：目录归属拒绝、SDK 逐层目录、安全路径 | 实际细粒度授权 |
| AC-05 | LOCAL_PASS：真实 ORM 活动/主版本过滤、稳定排序键、权限后分页 | MySQL/DM8 方言与大数据翻页 |
| AC-06 | LOCAL_PASS：只对有权候选查询正文；SDK 名称/正文模式；候选续页代码审查 | 真实 ES 分词、代次投影及大结果完整性 |
| AC-07 | LOCAL_PASS：未解析/拒绝不读正文，SDK 状态回查 | 真实各类文件解析状态 |
| AC-08 | LOCAL_PASS：E04/E08、内容代次游标、旧入口解析器回归 | 当前真实投影/预览产物与并发换版 |
| AC-09 | LOCAL_PASS：只预览、不签原件、显式 original 拒绝 | 真实对象和外部访问地址；原件仍走已有水印下载 |
| AC-10 | LOCAL_PASS：新旧名称共享检索、合法 filters、原 Filelib 空结果/来源回归 | 真实模型与 ES/Milvus 检索 |
| AC-11 | LOCAL_PASS：UTF-8 正文字节、Owner/dispatch 参数、指定目录、受理状态 | 真实分类、版本、权限元组与积分链路 |
| AC-12 | LOCAL_PASS：Base64 字节保真、同一 Owner 流程、SDK 上传回查 | 真实 Redis 原名映射和 MinIO 暂存 |
| AC-13 | LOCAL_PASS：真实 50 MiB/10 MiB 领域边界、UTF-8 超限、非法输入；请求流在缩小预算下验证有/无长度头超限，另断言生产 80 MiB 常量 | 完整 80 MiB HTTP 边界、代理限制、并发峰值内存和临时磁盘容量 |
| AC-14 | LOCAL_PASS（适配层）：无权/越界/重复拒绝、旧失败 ID 不报成功；复用既有配额和权限回归 | 真实配额回滚与并发重复竞争；Owner 原有并发去重能力不升级 |
| AC-15 | LOCAL_PASS（故障注入）：暂存取消清理、提交交接保护、未知投递状态保留已知 file_id | 真实 OpenFGA 补偿、broker 故障、进程终止恢复 |
| AC-16 | LOCAL_PASS：SDK 并发租户隔离/取消、请求 session 释放与实际任务身份 | 真实多租户及 Worker headers 上下文 |
| AC-17 | LOCAL_PASS：未知/嵌套身份字段拒绝、错误和日志脱敏、不返回原始计数 | 生产日志与存储策略验收 |
| AC-18 | LOCAL_PASS（本次变更）：旧 MCP/Token/Filelib/来源/解析投递与 CORS 回归；E10 证明六个旧失败 | 存量失败仍未修复，真实部署兼容性 |

## 5. 受控端到端与人工验收

`test_mcp_knowledge_flow.py` 使用实际 FastMCP/ClientSession、生产 tool factory、新领域服务、SQLite 仓储及真实 canonical 解析器。OwnerPort 写入专属内存数据库，StoragePort 保存实际字节，解析完成由受控状态更新模拟。检索外部端口与权限结果受控；不能把 OwnerPort 当作真实入库事务、FGA 或 Celery 的替代验收。

流程覆盖：发现空间 → 列目录/文件 → 搜索 → 正文/预览/片段；创建 Markdown 和上传 Base64 → 查询排队状态 → 模拟完成 → 回读正文；重复拒绝、另一租户拒绝、session/暂存资源清理。

项目 E2E 模板的 JWT、REST 外壳和 GET 查询改为 F070 已有的 Token、MCP 原生结构和工具回查，避免改动共享 REST helpers。本功能无页面，不需要新增前端验收。

以下均为 `MANUAL_REQUIRED`，未执行：

1. 在隔离测试租户配置真实 `/mcp` Token，验证公共、部门、团队、科室、已有个人空间及收藏只读能力。
2. 通过部署后的代理，用真实 MinIO/Redis 上传非敏感测试文件，确认原名、目录、业务域、标签、版本/授权、配额及实际 Celery 解析结果；用新工具回读与检索。
3. 检查发布/分享入口的当前代次、撤销后的拒绝，以及预览地址可达；原件继续走现有水印流程。
4. 验证临近 50 MiB 文件的完整 HTTP 请求、80 MiB 拒绝、并发峰值内存/磁盘和超时。SDK 会解析完整 JSON，未做吞吐或资源压测。
5. Linux/CI 的真实 DM8 与 MySQL 查询；macOS 无 DM8 驱动。本次没有迁移，不代表数据库方言已经实测。
6. 使用专属测试数据注入授权写失败和投递不确定，确认既有补偿与 Worker 租户上下文。禁止用正式文件做破坏性故障演练。

## 6. 静态门禁

24 个变更 Python 文件执行 `ruff check` 和 `ruff format --check`：`All checks passed!`、`24 files already formatted`。15 个生产文件逐一执行 `scripts/arch-guard.sh`，无告警或 VIOLATION，并通过 AST 语法检查。

九份特性文档的相对链接、10 个 JSON 示例和 Python 示例语法通过检查；所有变更 Python/Markdown 文件的尾随空白与 `git diff --check` 通过。任务 ID/依赖、REQ/AC 追溯与实际文件范围已核对，T001～T018 完成，本次没有更改配置/依赖/Schema。代码自审见 [code-review.md](code-review.md)。

回退方式为回退本次应用改动；无需回退表结构。已经通过业务上传创建的文件保留，不能声称回退代码会撤销数据。

## 7. get_file_source 缺陷修复（2026-10-16）

- 基线：`feat/2.5.0-sg` / `74dc97768`；本节对应未提交工作区的 T019～T020。
- 状态：`LOCAL_PASS_WITH_BASELINE_FAILURES / DEPLOYMENT_NOT_VERIFIED`。
- 前序运行环境证据：空间 317 的文件 9992556（Markdown）及四个 DOCX 均返回 `Resource denied or unavailable`；正文读取及检索成功。前序报告在 `/tmp/bisheng-mcp-live-verification-20261016.md`，不包含 Token、签名链接或正文。
- 已证实的代码根因：MCP 只调用 `resolve_preview_object_name` 并检查对应对象，绕过预览 Owner。该 helper 对无派生预览的 Markdown/PDF 返回空；Office 路径遗漏 `get_file_share_detail` 已支持的 PDF 元数据、统一 PDF 产物及 HTML 来源。这些可用来源在本地用例中仍触发旧错误。运行环境五个文件的实际权限/对象状态未读取，不能断言它们均为同一具体失败分支。
- 修复：保留 MCP 原授权与 canonical 预览门禁，使用原始入口 ID 调用 `KnowledgeSpaceService.get_file_preview`；只映射来源 DTO，保留签名，补齐相对链接的现有存储分享域名。原生文本/PDF/常见图片沿用页面的原生预览地址；Office 仅剩原件时仍拒绝，显式 original 及无权限请求不新增签名或下载通道。

| Evidence | 范围及命令 | Result |
|---|---|---|
| E14 红灯 | `.venv/bin/python -m pytest test/knowledge/test_mcp_knowledge_content_service.py -q --tb=short`，生产修复前 | 10 failed、9 passed，4.24 秒；缺少 Owner 预览来源及权限委托 |
| E15 绿灯 | 同一内容测试 + `test/mcp_server/test_mcp_knowledge_flow.py` | 20 passed、10 warnings，4.09 秒 |
| E16 模块回归 | 下列核心命令，包含真实 SDK/ASGI/TCP、SQLite 及入口解析器，外部端口受控 | 100 passed、105 warnings，11.08 秒 |
| E17 扩大回归及基线对照 | 核心命令 + 下列预览回归；相同命令在 `git archive HEAD src/backend` 的隔离快照执行 | 当前 109 passed、7 failed，17.13 秒；HEAD 95 passed、同样 7 failed，17.55 秒；失败测试 ID 集合相同 |
| E18 静态/审查 | 三个变更 Python 文件的 Ruff 检查/格式；生产文件架构守卫；`git diff --check`；文档引用/示例语法 | PASS；无新增依赖、配置、Schema 或权限策略 |

核心命令（cwd 为 `src/backend`，Python 3.10.19，现有 `.venv`）：

```bash
.venv/bin/python -m pytest test/mcp_server \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py \
  test/knowledge/test_knowledge_document_entry_resolver.py -q --tb=short
```

扩大回归在核心命令中追加：

```text
test/knowledge/test_dept_admin_member_personal_preview.py
test/knowledge/test_department_file_view_content.py
test/test_knowledge_space_service.py::TestTupleLifecycle::test_get_file_preview_uses_knowledge_file_can_read
test/test_knowledge_space_service.py::TestTupleLifecycle::test_get_file_preview_schedules_success_telemetry_without_changing_response
test/test_knowledge_space_service.py::TestTupleLifecycle::test_get_file_preview_skips_my_knowledge_read_for_portal_bff_proxy
test/test_knowledge_space_service.py::TestTupleLifecycle::test_get_file_preview_denied_without_view_file_permission
```

七个基线失败为：部门管理预览测试的两个过期异步 mock/断言、部门文件预览测试的两个数据库/KnowledgeRag 替身缺口，以及旧知识空间预览的两个完整响应等值断言和一个未隔离数据库调用。本次未修改这些 Owner 方法或旧测试，也未隐藏失败。日志分别保存在 `/tmp/bisheng-mcp-source-fix-core-20261016.log`、`/tmp/bisheng-mcp-source-fix-regression-20261016.log`、`/tmp/bisheng-mcp-source-fix-baseline-20261016.log`。

AC-09-FIX、AC-09、AC-17、AC-18 的本地回归为 PASS（E15～E18）。本次未提交、推送或部署，未新增运行环境探测，未调用两个远程写工具。部署后需以同一 Token 复测上述文件的 auto/preview、显式 original 拒绝及预览链接可达性；真实 MinIO/FGA、MySQL/DM8 和五个文件的实际产物仍为 MANUAL_REQUIRED。若 Owner 自身没有可用预览，工具继续安全失败，不通过强制生成产物或签发 Office 原件掩盖问题。

## 8. 目录 ID 字符串兼容（2026-10-22）

- 基线：`feat/2.5.0-sg` / `3e7dd9049`；T021～T022，本节状态 `LOCAL_PASS / DEPLOYMENT_NOT_VERIFIED`。
- 复现：本地原 tools/list 及请求模型使用严格正整数。客户端传 `folder_id="305"` 或 `"000305"` 时，真实 SDK 在进入领域服务前拒绝；客户端所述外部字符型定义/缓存未读取。
- 修复：独立 `FolderId` 同时接受严格正整数和格式为 `^0*[1-9][0-9]*$` 的字符串，再用 `AfterValidator(int)` 归一化。四个顶层参数和嵌套 FolderScope 与请求模型统一采用此别名；工具 schema 展示 integer/string，顶层另外允许 null。响应与其他资源 ID 保持原类型。

| Evidence | Command / Scope | Result |
|---|---|---|
| E19 红灯 | `pytest test/mcp_server/test_mcp_tools.py -k 'folder_id_is_normalized or schemas_and_annotations' -q --tb=short`，生产修改前 | 3 failed、2 passed，9.01 秒；工具 schema 缺 string，两种数字字符串被拒绝，整数和根目录通过 |
| E20 绿灯 | `.venv/bin/python -m pytest test/mcp_server/test_mcp_tools.py -q --tb=short` | 初次 32 passed，5.51 秒；补充嵌套 null 拒绝/省略根目录并整理等价测试写法后，最终 33 passed、40 warnings，4.53 秒 |
| E21 最终相关回归 | 下列完整命令；最终 Python 代码状态 | 115 passed、64 warnings，14.14 秒；含真实 SDK/ASGI/TCP、SQLite、现有目录归属及上传权限路径，外部业务端口受控 |
| E22 静态与自审 | 五个变更 Python 文件 Ruff check/format；四个生产文件架构守卫；AST、文档引用/示例及 `git diff --check` | PASS；无新依赖/配置/表结构，无新增权限或目录策略 |

命令在 `src/backend` 执行，使用已有 `.venv` / Python 3.10.19：

```bash
.venv/bin/python -m pytest test/mcp_server \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py -q --tb=short
```

AC-FOLDER-ID、AC-04/05/06/11/12/17/18 在本次相关范围为 PASS。SDK 覆盖五工具参数在进入服务前成为 int、普通及前导零字符串、旧整数调用、顶层 null/省略根目录、嵌套 null 拒绝；非法输入不打开业务服务，其他资源 ID 的字符串仍拒绝。领域回归保留跨空间目录和上传拒绝；没有修改权限检查来适配输入。

日志：`/tmp/bisheng-mcp-folder-id-red-20261022.log`、`/tmp/bisheng-mcp-folder-id-final-targeted-20261022.log`、`/tmp/bisheng-mcp-folder-id-final-regression-20261022.log`。本次初始 Ruff 提示测试字典构造和全角测试字符已修正，最终五文件静态检查通过。

未提交、推送、部署或远程创建/上传业务文件。真实数据库/权限/存储及外部客户端缓存仍未验收；部署后需刷新工具清单，以 `folder_id="305"` 在有权测试目录验证。旧工具清单若被手工配置或缓存，不会因本地代码修改而自动刷新。回退本次局部改动即可；历史扩大回归的存量失败保留于前文，本次 115 项不代表全仓全量测试。

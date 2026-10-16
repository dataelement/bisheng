# MCP 九工具代码审查

- 基线：`feat/2.5.0-sg-main` / `06bc21e27`。
- 范围：工作区 15 个生产 Python 文件、9 个测试 Python 文件和本特性文档；包含未跟踪新文件，不能仅用 HEAD 之间的 diff 代替审查。
- 方式：执行者按项目 task-review、code-review 清单自审；没有独立 agent 审查。
- 结果：`PASS_WITH_WARNINGS`，本地实现完成；真实基础设施与压测仍待验收，六个存量回归失败未修复。
- 证据：[verification.md](verification.md)。

## 1. 任务级约定审查

下表按任务归并记录六项检查。所有任务均核对声明文件存在、无范围外生产改动；测试和前置依赖依据实际执行结果完成，详见 tasks 与 verification。前端检查全为 N/A。

| 任务 | 架构 | 命名 | 序列化 | 数据库 | 信息泄漏 | 配对/依赖与结果 |
|---|---|---|---|---|---|---|
| T001、T004、T007、T009、T015、T016 | N/A | PASS | N/A | N/A | PASS | 测试任务，AC 标注及对应红/绿灯存在；PASS |
| T002、T003 | PASS | PASS | PASS | N/A | PASS | 严格输入模型、统一执行/错误边界，T001/T009；PASS |
| T005 | PASS | PASS | N/A | PASS | PASS | BaseRepository 接口/实现，真实 ORM 用例 T004；PASS |
| T006 | PASS | PASS | PASS | PASS | PASS | 服务无 SQL，通过 Repository/原权限 Owner，T004；PASS |
| T008 | PASS | PASS | PASS | PASS | PASS | 正文和来源先授权，物理内容解析后读取，T007；PASS |
| T010 | PASS | PASS | PASS | PASS | PASS | 原 Owner 入库/授权/版本/解析，受控暂存，T009；PASS |
| T011、T012 | PASS | PASS | PASS | N/A | PASS | MCP 原生结果、显式签名、注解、严格 schema，T001；PASS |
| T013、T014 | PASS | PASS | PASS | PASS | PASS | 每请求装配/session、鉴权后有界接收，T001/T015；PASS |
| T017、T018 | N/A | PASS | N/A | N/A | PASS | 文档区分本地、存量失败、真实环境与部署；PASS_WITH_NOTES |

序列化按已确认 MCP 契约使用 `CallToolResult/structuredContent`，列表为游标页，而非 REST 的 `UnifiedResponseModel/PageData`。认证也沿用 F070 的 `X-Developer-Token` 和实际工具任务身份作用域，不改为 JWT Depends。这些是既有 MCP 协议边界，不属于绕过权限。

只读候选复用已有 `KnowledgeFileDao.active_inventory_predicate()` 纯查询表达式，没有新增 DAO 入口；所有新 SQL/ES 查询仍封装在 Repository。未新增模型、错误码、迁移、依赖、配置或 Worker。

## 2. 特性级六维审查

| 维度 | 结论 | 证据与判断 |
|---|---|---|
| 边界条件 | PASS | 严格正整数、未知字段/嵌套身份字段拒绝、数量/长度在 schema 与模型一致；50/10 MiB 按字节；HTTP 实际计数；空结果/预算续页/版本游标；有界正文和读写超时 |
| 权限与认证 | PASS（本地） | 空间可见与文件读、目录/空间上传权分别判断；目录归属与租户校验；新 retrieve 先检查全部空间；只读不补库/改状态；来源不签原件；创建授权仍归 Owner |
| 并发安全 | PASS_WITH_WARNINGS | factory 每请求创建服务/缓存/session；身份在实际 SDK 任务建立并复位；暂存取消与已提交交接分阶段，未知投递不删除业务文件；强并发去重和跨系统事务能力继承 Owner，尚无真实压测 |
| 信息泄漏 | PASS（本地） | 白名单元数据、授权后才查正文/签名；错误固定安全文本；不记录 Token、Base64、正文、URL 或原始异常文本；投递不确定日志保留用户/文件 ID 及异常类型供恢复定位 |
| 测试证据 | PASS_WITH_WARNINGS | 真实 SDK/ASGI/TCP/SQLite 与新服务覆盖成功、拒绝、版本、取消和故障边界；相关回归有六个 HEAD 已有失败；真实依赖尚未验收 |
| 代码风格与分层 | PASS | 24 文件 Ruff、15 生产文件架构守卫；无 Service ORM、跨 API 导入或新手写租户 WHERE；只复用上传/检索 Owner，没有调用自身 HTTP 或 file/sync |

## 3. 审查中已修复的问题

1. 分块正文恰好在页边界截断时丢失分隔符。以失败用例复现，游标改为记录分隔符在分块文本中的真实偏移，跨批次保留 lookahead。
2. 隐藏祖先之下的可写目录可能让空间被错误标为可定位的上传目标。加入完整有权祖先路径比较，红/绿灯验证。
3. 新 `retrieve_chunks` 继承的嵌套过滤模型原本忽略未知身份字段。使用新工具专属严格子模型，不收窄旧检索的嵌套契约。
4. 部分函数签名未展示请求模型的长度/数量限制。提取共享类型别名，使 tools/list 的 schema 与运行时限制一致，协议用例先失败后通过。
5. broker 投递异常返回已知 ID，但审计未直接包含该 ID。补充仅含用户/文件 ID 和异常类型的日志；回归同时断言原始异常文本不泄漏。

## 4. 保留事项

- **MEDIUM：真实基础设施与资源验收未执行。** 受控外部端口不能证明实际上传事务、FGA 补偿、ES/Milvus 查询、Worker 解析或代理能力。人工步骤见 verification §5，不能宣称已上线验收。
- **MEDIUM：扩大回归仍有六个已有失败。** HEAD 快照复现相同测试和原因；保留记录，不为本功能修改旧业务域语义或旧测试装配。
- **兼容性维护：SDK 内部元数据。** 严格参数模型沿用现有 `_tool_manager` 装配方式，依赖当前锁定 MCP SDK。将来升级 SDK 时复跑 tools/list、参数拒绝和生命周期测试。
- **来源能力边界：** 原件要求既有水印下载流程。新来源工具提供有权预览并说明原件不可用；显式 original 拒绝，不新增下载票据服务。
- **性能边界：** 文件候选每批 100、每请求最多扫描 1000 后返回续页；可写空间发现可能遍历多个目录，受操作超时约束。完整 JSON 的内存峰值、并发大上传和大目录耗时没有压测结果。

没有发现本次新增的未修复 HIGH 级问题。此结论限定为所审源码和本地测试证据，不是合并、部署或生产验收授权。

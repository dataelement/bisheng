# MCP 知识空间工具：需求与验证追溯

- Feature ID: `078-mcp-knowledge-tools`
- Status: `IMPLEMENTED_LOCAL`
- Mode: `spec-then-implement`
- Created: `2026-10-16`
- 权威行为及 API 契约：[spec.md](spec.md)。背景、截图需求和已确认选择：[spec-discovery.md](spec-discovery.md)。

## 范围与确认记录

用户确认只覆盖知识空间，现有文件通过客户端 Base64 传入。包括截图九工具，保留旧 `search_knowledge`；不含传统库的新工具支持、覆盖/删除/发布/分享、创建目录、身份代理、URL 下载和管理页面。

用户于 2026-10-16 要求增大原先建议的大小限制；最终采用解码文件 50 MiB、文本 10 MiB UTF-8、HTTP 请求体 80 MiB。文件上限对齐现有普通文档上传的源码默认值，仍受现有更严格的上传规则和配额约束。用户随后整体确认规格和实施，包含写入能力扩展及来源策略。

## 需求及验收方法

2026-10-16 用户明确确认按调整后的限制实施九工具，整份规格及写入能力已获授权；后续不重复请求阶段确认。

所有验收 ID 的具体可观察结果以 spec 的唯一验收表为准。下列每条 REQ 均有 AC 和验证方法，实际执行结果见 [verification.md](verification.md)。

| Requirement | 需求 | Acceptance | Verification ID | Method / Evidence target |
|---|---|---|---|---|
| REQ-001 | 统一 MCP 认证、十名称和旧检索兼容 | AC-01、AC-02 | V-PROTOCOL | 真实 SDK / HTTP 鉴权及 schema 集成，更新 `test/mcp_server/test_mcp_server.py` |
| REQ-002 | 按名称及上传能力发现有权空间 | AC-03 | V-BROWSE | 查询服务验证权限后分页、根不可写但子目录可写；`test/knowledge/test_mcp_knowledge_query_service.py` |
| REQ-003 | 目录路径、层级分页及细粒度上传能力 | AC-04 | V-BROWSE | 同一查询服务批次覆盖跨空间目录、只读父目录与可写子目录 |
| REQ-004 | 文件列表的目录、排序、状态和活动版本 | AC-05 | V-BROWSE | 查询服务批次覆盖无读写副作用、权限过滤和页边界；验证仓储排序兼容 |
| REQ-005 | 按名称/正文及空间/子树范围搜索文件 | AC-06 | V-SEARCH | 查询服务与范围受限的搜索仓储集成；只读/发现/分发入口权限案例 |
| REQ-006 | 文件详情、解析状态和有界 canonical 正文 | AC-07、AC-08 | V-CONTENT | `test/knowledge/test_mcp_knowledge_content_service.py`，覆盖物理/逻辑入口、版本变化、无正文和续页 |
| REQ-007 | 获取有权来源，保持预览与下载策略 | AC-09 | V-CONTENT | 同一内容服务批次覆盖只预览、无下载、分享限制、水印限制和拒绝不签发 |
| REQ-008 | 新名称复用片段检索并保留旧契约 | AC-10、AC-02 | V-PROTOCOL | SDK 两名称实调及现有 Filelib 检索/来源/知识空间检索回归 |
| REQ-009 | 文本和 Markdown 新文件保存 | AC-11 | V-WRITE | `test/knowledge/test_mcp_knowledge_ingestion_service.py`，核对入库位置、字节、owner/version/dispatch |
| REQ-010 | Base64 上传及输入/请求体边界 | AC-12、AC-13 | V-WRITE、V-PROTOCOL | 领域入库批次验证二进制完整性、格式及 50 MiB 文件/10 MiB 文本边界；ASGI 请求流验证 Content-Length 缺失时的 80 MiB 实际体积上限 |
| REQ-011 | 写入权限、配额、冲突和副作用阶段恢复 | AC-14、AC-15 | V-WRITE | 参数化拒绝、重复/并发、入队前失败、入队后断连与投递不确定状态；不承诺 exactly-once |
| REQ-012 | 租户隔离、字段安全及原系统兼容 | AC-16、AC-17、AC-18 | V-PROTOCOL、V-REGRESSION | 实际 SDK 任务并发/断连、字段拒绝和日志检查；复用当前 Token、Filelib、权限、上传/投递与 CORS 回归 |

## 非功能要求

### 2026-10-16 来源工具缺陷修复（REQ-007 / AC-09）

- 当前错误：部署环境中空间 317 的 Markdown 和 DOCX 文件调用 `get_file_source` 返回安全错误；本地代码只按传统预览对象路径签名，未复用现有预览服务。
- 期望：通过 MCP 的空间、文件及 canonical 预览权限校验后，沿用 `KnowledgeSpaceService.get_file_preview` 的来源。支持现有 PDF/HTML/普通预览及文本、PDF、图片的原生预览；不直接回退下载 Office 原件。
- 范围：只修复 `get_file_source`，不修改预览 Owner、权限策略、下载流程、数据或配置。生产文件的实际存储状态仍需部署后验证。
- 回归验收 AC-09-FIX：缺少传统预览对象但 Owner 返回有效预览时成功；逻辑入口传入原始入口 ID；权限拒绝及显式 original 在调用 Owner 前失败；Office 仅剩原件或无任何预览时仍失败；不泄露原件、管理入口及业务元数据。
- 验证：参数化领域回归、现有 SDK 流程、入口解析及预览权限回归；记录红灯、绿灯和部署边界。

- NFR-001：所有列表、正文和请求体有明确上限；权限过滤发生在返回及分页结果确定前，不返回原始候选总量。
- NFR-002：读取操作不补建个人库或修正文件状态。元数据只返回白名单字段，签名 URL、Base64、正文和 Token 不进入普通日志。
- NFR-003：实际工具任务建立绑定身份，数据库与请求资源有可观察的释放路径；写入取消按照已发生副作用处理。
- NFR-004：不新增业务表和依赖；新增查询使用 Repository，保持 MySQL/DM8 兼容，不手工增加 ORM 租户过滤。
- NFR-005：本地替身测试不能代表真实 MySQL/DM8、OpenFGA、Redis、MinIO、ES/Milvus、Worker 或线上代理验收。
- NFR-006：Base64 解码后文件上限为 50 MiB，文本按 UTF-8 字节上限为 10 MiB；整个 HTTP 请求体上限为 80 MiB，容纳 Base64 或 JSON 字符转义的膨胀。解析、解码与并发的内存开销须在实施验证中观察，不能把分块解码等同于 SDK 全链路流式上传。

## 风险与验证边界

最大的权限风险是从“库可见”推断“文件可读/可写”，以及把旧来源链接或同步上传当成通用业务入口。最大的可靠性风险是 SDK 断连取消发生在数据库、对象存储、权限和队列的不同阶段。必须覆盖拒绝、部分失败和并发，不能只跑成功路径。

本地已执行浏览、正文、写入、协议、真实 ORM/SDK 流程和相关回归，308 项通过、6 项已有失败；六项均在未修改 HEAD 复现。真实基础设施、代理、DM8 和生产验收为 `MANUAL_REQUIRED`，不以本地受控端口替代。详见 [verification.md](verification.md)。

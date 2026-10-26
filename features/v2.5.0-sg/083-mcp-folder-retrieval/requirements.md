# F083：需求与验收追溯

- Feature ID: `083-mcp-folder-retrieval`
- Status: `IMPLEMENTED_LOCAL`
- Mode: `spec-then-implement`
- Created: `2026-10-26`
- 权威行为：[spec.md](spec.md)；设计：[design.md](design.md)。

## 1. 澄清与确认记录

2026-10-26 用户选择“单个知识空间内的单个文件夹”和“默认包含全部子文件夹，可通过 recursive=false 仅检索当前层”，随后确认发现文档范围进入完整规格设计。

用户在完整规格评审后回复“开始实施”，确认 1000 个成功候选文件预算和严格过滤契约，并授权实现与本地验证。任务已完成，本地 400 项相关测试通过；不提交、合并、推送或部署。

## 2. 需求映射

| Requirement | 需求 | Acceptance | Design | Verification |
|---|---|---|---|---|
| REQ-001 | 新增只读 retrieve_folder_chunks，单空间/单目录；严格参数与身份契约 | AC-01 | D-01、D-04 | V-PROTOCOL |
| REQ-002 | 默认递归，false 仅直接文件；路径按完整分隔符边界判断 | AC-02 | D-02 | V-SCOPE |
| REQ-003 | 完整枚举候选，跨批不遗漏；空范围短路，不得视为未设过滤 | AC-03、AC-06 | D-02、D-03 | V-SCOPE、V-RETRIEVAL |
| REQ-004 | 沿用目标账号/租户、空间/目录归属和逐文件权限，拒绝路径无泄漏 | AC-04 | D-02、D-04 | V-PERMISSION、V-FLOW |
| REQ-005 | 标签与目录取交集，在召回前限域，canonical 回映射严格留在显式入口内 | AC-05 | D-01、D-03 | V-RETRIEVAL |
| REQ-006 | 保留当前 canonical 版本、代次、授权与来源链接语义及原片段响应 | AC-05、AC-06 | D-03 | V-RETRIEVAL |
| REQ-007 | 1000 成功候选及 30 秒总时限，超限失败无静默截断、重试或无范围降级 | AC-03、AC-06 | D-02、D-04 | V-SCOPE、V-FLOW |
| REQ-008 | 复用现有内部链路，旧 MCP/REST、Token、身份及 CORS 行为兼容 | AC-01、AC-07 | D-03、D-04、D-05 | V-REGRESSION |
| REQ-009 | 只读、无业务写入，审计安全且异常/取消后资源与上下文释放 | AC-04、AC-06、AC-07 | D-02、D-04 | V-PERMISSION、V-FLOW |
| REQ-010 | 文档覆盖参数、标签交集、递归/当前层、预算、返回及错误行为 | AC-07 | D-05 | V-DOC |

## 3. 验证组

| Verification | 主要层级 | Evidence Target / 验证目标 |
|---|---|---|
| V-PROTOCOL | V2，真实 SDK schema/调用 | `test/mcp_server/test_mcp_tools.py`：十一工具发现；新工具必填字段、folder_id 归一化、strict boolean、未知参数和非法过滤拒绝；旧工具集合保持 |
| V-SCOPE | V2，仓储/领域范围 | `test/knowledge/test_mcp_knowledge_repository.py` 与新增 `test/knowledge/test_mcp_folder_retrieval_service.py`：递归路径、兄弟/相似目录隔离、多批、空集、恰好 1000 及第 1001 个候选拒绝，超过预算不执行检索 |
| V-PERMISSION | V2，领域授权边界 | 新目录范围服务测试：目标账号权限、无权目录/跨空间/跨租户拒绝、后代文件拒绝、权限异常传播；不写业务数据、不返回明细 |
| V-RETRIEVAL | V2，共享服务与回映射 | `test/open_endpoints/test_filelib_retrieve_service.py`、`test/knowledge/test_knowledge_space_chat_service_retrieve.py`，按需要复用 `test_knowledge_retrieval_scope_resolver.py`：召回前 file_ids 与标签交集、空集不放大、strict_explicit 生效、目录外入口不回退、版本与来源响应不变 |
| V-FLOW | V3，受控 SDK 端到端 | `test/mcp_server/test_mcp_knowledge_flow.py`：真实 SDK + SQLite/实际范围仓储/共享服务装配，检索后端和权限外部端口受控；验证同目录默认/false 请求、目标身份、拒绝、超时/取消和清理 |
| V-REGRESSION | V2/V3，相关回归 | 复用 MCP、身份、Developer Token、知识 MCP、共享检索及 Filelib 原接口的相关测试；与原基线失败分开记录 |
| V-DOC | V0，文档/静态 | 规格/设计引用、JSON 示例、REQ/AC/设计映射、diff 范围；实施时补使用文档和 Ruff/架构检查 |

同一行为以一个主要测试层为证据；路径 SQL、SDK 参数、共享范围透传是独立边界，按上述风险划分，等价输入参数化，不按十一个工具复制全链路用例。同一代码状态的成功证据复用，不为每条 AC 重跑命令。

## 4. 非功能与边界

- 不引入固定吞吐/延迟承诺或覆盖率门槛；容量上限控制候选规模，不证明 1000 文件必定可在 30 秒内完成。
- 目录枚举采用调用内范围，最终权限沿用现有行为；不承诺多存储原子快照或进行中目录移动的强一致隔离。
- 不新增授权规则，不把门户发现/元数据可见性当作正文权限；空范围成功和主链路失败必须可区分。
- 真实 MySQL/DM8、OpenFGA、MinIO、Milvus/ES 和部署代理验收均为后续条件性验证；当前 macOS 不能证明 DM8 驱动执行通过。

## 5. 规格质量门

- [x] REQ-001～010 均有 AC、设计要素和验证组。
- [x] AC-01～07 均有可观察结果及验证方式，允许共享证据。
- [x] 范围、排除项、预算、空状态、拒绝、异常、兼容及回退明确。
- [x] 所有领域 Owner 保持，无新增 Schema/配置/依赖或旁路授权。
- [x] 完整规格获用户确认；实际行为验证与设施边界已记录在 verification.md。

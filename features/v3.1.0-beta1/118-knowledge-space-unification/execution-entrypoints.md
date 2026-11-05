# WF 后续运行准入：已核实事实与待冻结边界

以下是后续运行准入的源码盘点，不声称运行已接线。文件行号为盘点快照，新增业务代码可能使行号移动，定位以函数名为准。

核对 checkout：`118-wave2-wf`，固定 checkpoint `b26c14bdf`（后续仅增 T284 红测试到 `800a12d9c`）。本波已完成写/版本接线；**T041/T042 尚未实施，不以当前保存/发布测试宣称运行入口闭合**。

| 真实入口 | 版本与 payload 事实 | 已有准入 / 后续接缝 |
| --- | --- | --- |
| `api/v1/workflow.py:360` → `api/services/workflow.py:1139` `run_once` | 接受实际 `node_data.data`，无 version ID；可为未保存节点。`BaseNodeData` 后经 NodeFactory 实例化运行。 | 保留 workflow `edit`。按传入节点提取目标作临时运行合法/可见/credential scope 校验；不建 source/index，不拿 current 索引证明未保存配置。 |
| `api/v1/workflow.py:379` WebSocket | 连接先检查 workflow `use`（由现 F048 兼容解释为 visible），随后进入共享 WorkflowClient。 | use 退役不能扩大具体身份、session、credential scope 或 preview 编辑条件。连接时只核 current 不能证明后续 message payload。 |
| `open_endpoints/api/endpoints/workflow.py:33` invoke → `workflow/domain/services/published_workflow_service.py:49` | 已有 `@open_api_scope('workflow:invoke', session=True)` 和业务 use gate；prepare 使用 `Flow.data` 并应用 `override` 写 Redis 队列（第90行），无真实版本 ID 存入 source 身份。 | 对真实执行版本校验已保存 `workflow_version` source / 摘要；override 若能改引用槽需另明确，不能将任意 override 视为索引内配置。保留开放平台 principal/session/data scope。 |
| `public_endpoints/api/endpoints/workflow.py:24` public WS → PublishedWorkflowService.validate_websocket_session(:146) | `public_execution` 解析身份；只验证 root 存在、chat session 所属，再 dispatch 共享 WorkflowClient。 | 需与普通 WS 一起在实际执行 payload 落 Redis 前准入，保留 guest/session 校验。 |
| `common/chat/clients/workflow_client.py:172` init_workflow | 第176行直接 `message.data`，flow ID 也可来自 message；第196行将 payload 写 Redis。`check_status(:93)` / `ensure_workflow_available(:246)` 主要查 live root、在线条件，未形成 payload→具体版本证明。 | 这是所有 WS 的实际 enqueue 接缝。**不能 common 新增 workflow/domain import**；需由装配层注入执行 Port，或另批准将业务 client 迁往 workflow 域。 |
| 平台 `pages/BuildPage/flow/FlowChat/ChatPane.tsx:22` | 发送当前画布 nodes/edges/viewport，未带 version ID，允许未保存预览。 | 保存版完整运行与未保存预览须分清真实语义，preview 保留 edit。 |
| Client `pages/appChat/workflowAutoRerun.ts:77` | 从 Flow.data 构造 init_data payload；同样未带 version ID。 | 保存版运行可经真实业务解析 version、校验 payload 摘要；不能猜 current 即 payload。 |
| `evaluation/domain/services/evaluation_service.py:190` execute_workflow_get_answer | :284 查 `evaluation.version` 对应 FlowVersion，再将其 data 写 Redis投同一 execute_workflow。 | 评测不新增 source；执行既有版本要核真实 workflow_version。不能只在 v1 websocket 验证。 |
| `worker/workflow/tasks.py:58` | 实际读取 Redis payload；FlowDao 只辅助 root tenant / config author。 | 不为任务建模型绑定。本轮按已确认口径不扩 worker 与用户后续修改的一致性方案；enqueue 前准入仍需完整。 |

已有目标读取并非全部等价“visible 已核”：LLM 节点 `get_bisheng_llm_sync` → `llm/domain/llm/base.py:77` → `llm/domain/share_fallback.py:61` 是租户/Root share 与模型可用读取；旧知识库 RAG 在 `workflow/common/knowledge.py:433` 由 user_auth 决定 check_auth，QA `workflow/nodes/qa_retriever/qa_retriever.py:30` 固定 check_auth=False；space 经既有 `space_flow_retrieval` 的 view_file 过滤，EDGE 所有权保持，不得绕开召回侧过滤。

另待统一的跨租户执行 seam：Child 能执行 Root 共享 workflow 时，source 的拥有租户为真实 Flow.tenant_id（可能1），调用者身份租户仍 Child。现 REF.assert_source_tenant 会拒绝不同 ContextTenant；应以已获准的真实业务资源导出的内部 source-owner read scope 读取索引，保留原 actor / credential scope，不放宽 REF 以任意请求 SourceKey 读外租户。

本波不自造临时 `workflow_version`、receipt、Owner 或 source tenant，不对 `metadata_filter.document_id` 猜物理文件 ID。

## 助手与后续依赖

当前助手新增、更新、删除、发布/ONLINE均进入同事务引用校验；T302仅防已指定模型ID缺失时默认回退。WS运行等共用Agent完整准入T283及Info保留失效原知识ID/状态T294–T295尚未完成：先由原actor/principal、业务Owner、系统可见/共享范围和credential收窄导出事务绑定的只读SourceOwnerScope，再读取真实所属tenant的source/version/config摘要，不修改ContextTenant、不构造自报source tenant或静态fake许可。REF所有写入口继续严格当前tenant。

下一波应先补独立合同/红测/实现卡，再接WF临时目标运行与保存版本证明、AS共用Agent和Info；上述剩余任务不得因本次保存/发布绿测而勾选。任务不建立独立模型绑定，worker在途外部IO与用户后续修改竞态仍按既定范围暂不治理。

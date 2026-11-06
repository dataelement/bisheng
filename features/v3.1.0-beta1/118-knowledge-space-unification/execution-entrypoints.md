# 运行准入：W2盘点与W3接线结果

原盘点基于W2固定b26c14bdf/800a12d9c，当时T041/T042/T283/T294/T295未实施。以下更新为W3真实接线，不把原盘点的假设当成现有授权能力。函数名为定位入口，不沿用已漂移行号。

| 实际入口 | W3接线 | 保持边界 |
| --- | --- | --- |
| v1 run_once → WorkflowService.run_once | prepare_node_preview后才NodeFactory线程执行，节点/input取已核深拷贝 | 原edit；临时refs无source/index/legacy借用 |
| v1 workflow WebSocket | 端点绑定BoundWorkflowExecutionPort，原identity经Manager到WorkflowClient | 完整图匹配走saved；原edit才preview；当前/非current版本规则不变 |
| public workflow WebSocket | 同Port且allow_preview=False，保原public/session/ONLINE门槛 | 不用任意body替真实保存图，不以public降级preview |
| v2 workflow invoke → PublishedWorkflowService | 原完整operator传prepare_saved，实际当前source/graph后才override/Redis | 非引用参数可覆盖，引用槽变化10996；原OpenAPI principal/credential/session/数据范围不改 |
| common WorkflowClient/ChatManager | Protocol传递，准入先于会话/WAITING/Redis/queue，所有动作与check_status保连接根 | 无新增domain/API反向import；缺Port10994，拒绝保业务code |
| 平台ChatPane | 可选execution_mode和实际version_id；消息仍允许完整未保存图 | 可选字段只作提示，不能授权；客户端旧消息由服务端完整匹配 |
| 客户端workflowAutoRerun | wire保持，后端同Port证明真实保存图 | 不猜current即请求payload；保持原在线/自动重跑开关 |
| JWT评测 | 原UserPayload进BackgroundTasks，调度/任务入口核真实owner/tenant；每题prepare_saved后才线程Redis | 精确存储正version，无current fallback，不恢复任意creator，不增加任务绑定 |
| AS共用Agent与ChatClient | init/run/stream/缓存各次准入实际配置links，publish复用外部SQL事务 | 不重建身份；初次失败无半成品缓存；配置变化清旧缓存并10998 |
| AS Info | GET保原knowledge_ids/裁剪状态，真实可展示knowledge_list | 写响应状态None=未查询，无commit后inspect；ACTIVE token只inspect且核真实会话 |
| API/worker启动 | 同一register装配真实WF/AS SourceOwner、KN/Model TargetOwner、原身份和同authority legacy Reader | 构造无业务IO；saved缺coverage/index仍拒，preview不读来源索引；不装fake/全许可默认 |

原跨租户盘点假设已纠正：真实生产共享适配目前支持llm_server，未发现可直接依赖的WF/AS Root业务共享拓扑。Root模型shared_with、继承默认或旧is_shared不推导WF/AS共享执行。来源候选仍按原C3可见/pin和实际业务权限获取；仅已授权来源导出的真实SourceOwnerTenant可供私有scope窄读目标/索引，不改ContextTenant/actor，也不接受请求自报tenant。原LLM可用性、knowledge_auth及space view_file召回过滤保持。

保存版在全部目标后核真实业务root/版本/links，并重验guard/source/raw和完整配置。临时预览在全部目标准入后核真实root/edit/current及canonical输入，不读取或要求来源index、coverage、legacy证据，也不创建来源。原scope与R2收据私有登记额外核原对象is，读取事实不可用于写绑定。详细接口与错误见[运行合同](./execution-read-contract.md)，交付/独立复核见[W3记录](./wave3-implementation-review.md)。

其余四类来源、Coverage实际适配/全量回填、目标删除协调和两端页面仍待实施；原分享生成授权 T404/T405 已移出本特性，见[独立待办](../../../docs/backlog/share-link-issuance-authorization.md)，不计入本次交付前置。任务不建立模型绑定，worker在途IO与用户后续修改竞态仍按用户确认范围暂不治理。

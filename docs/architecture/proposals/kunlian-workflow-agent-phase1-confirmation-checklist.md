# 昆联 × 毕昇 Workflow 待联调接口清单

## 主流程必需

| 编号 | 接口／协议 | 业务用途 | 请昆联确认 |
| --- | --- | --- | --- |
| K-01 | **调用鉴权与用户身份传递**（现有 SSO／`invoke`） | 昆联按实际运行用户执行 Agent。昆联代用户查询或授权毕昇工作流时，毕昇也能识别操作者。 | 优先确认 `invoke` 能否复用 SSO Access Token，如何验证用户与租户。若无法复用，请说明现有机制。另请确认昆联代用户调用毕昇时的身份和授权范围。 |
| K-02 | **身份目录及增量** `GET /identity/tenants`、`GET /identity/users`、`GET /identity/memberships` | 同步租户、用户及成员关系，更新归属和停用状态。 | 全量初始化、增量分页、停用标志及用户组成员的表达方式。 |
| K-03 | **授权资源列表与版本详情** `GET /resources`、`GET /resources/{resource_type}/{resource_id}/versions/{version_id}` | 编辑工作流时，用户选择有权使用的 Agent、模型、知识库、Skill、工具或连接器，并按版本配置输入输出。 | 支持的资源类型、权限过滤、版本状态及输入输出 Schema。 |
| K-04 | **资源权限预检** `check`／`batch_check`，路径待确认 | 保存、测试或发布前，判断当前用户能否使用指定资源版本。 | 用户、租户、版本、动作及允许或拒绝结果。 |
| K-05 | **创建资格和配额**，接口或可信网关机制待确认 | 新建工作流时检查创建资格、平台策略和剩余配额。 | 校验方式、配额规则和拒绝原因。 |
| K-06 | **Agent 同步执行** `POST /agent-runtime/invoke` | 执行发布时锁定的 Agent 版本，将同步结果交给下游节点。 | 版本、实际用户、输入输出、运行 ID、错误、超时和幂等规则。 |
| K-10 | **发布依赖环路检查** `POST /dependencies/cycles:check` | 发布前发现跨 Agent／Workflow 的循环依赖，阻止形成环路的版本发布。 | 检查范围、请求格式和环路结果。 |
| K-13 | **Workflow 变更同步**，昆联接收、订阅或拉取 | 工作流权限、所有者和发布版本变化后，更新昆联侧的权限镜像和版本信息。 | 同步方式、鉴权、游标、重试和补偿。 |

## 按场景需要

| 编号 | 接口／协议 | 启用场景与业务用途 | 请昆联确认 |
| --- | --- | --- | --- |
| K-07 | **模型推理** `POST /model-gateway/chat/completions` | 毕昇模型节点直接调用昆联模型，获取生成内容。 | 模型版本、用量和流式响应。 |
| K-07 | **知识库检索** `POST /knowledge/retrieve` | 毕昇检索节点直接查询昆联知识库，获取用户有权访问的片段和引用。 | 知识库选择、用户数据权限、命中和引用字段。 |
| K-08 | **工具／连接器调用** `POST /capabilities/invoke` | 毕昇工具节点直接调用昆联能力，查询或写入业务系统。 | 调用状态和写入幂等规则。 |
| K-06／09 | **Agent 异步执行与跟踪** `POST /agent-runtime/invoke`、`GET /agent-runtime/runs/{agent_run_id}`、`GET …/events`、`POST …/cancel` | Agent 运行时间较长时，通过运行 ID 查结果。按需订阅进度或申请取消。 | 异步返回、终态查询、事件和取消结果。 |
| K-09 | **Agent 人工交互**，运行路径下的 `GET …/interactions/{interaction_id}`、`POST …/interactions/{interaction_id}/complete` | Agent 等待人工输入时，查询表单并提交答案，继续运行。 | 交互 Schema、重复提交和修订冲突。 |
| K-10 | **依赖方与影响查询** `GET /dependencies/dependents`、`GET /dependencies/impact` | 停用或归档跨资产引用的版本时，查看哪些资产会受影响。 | 查询范围及结果字段。 |
| K-11 | **业务回执查询** `query_receipt`，路径待确认 | 外部写入或异步操作的响应丢失时，查原操作是否执行及其结果。 | 按幂等键或业务回执查询的规则。 |
| K-12 | **文件传输**，平台文件 API 或 S3 | 两端要传递附件或生成文件时，上传、引用和下载文件。 | 对象引用、下载授权和签名 URL。 |
| K-13 | **Session 回调**，通道待确认 | 需要主动通知对方 Session 事件时，推送运行状态。 | 回调方向、事件字段和鉴权。 |
| K-14 | **反向调用的版本绑定**，查询、同步或可信签名 | 昆联 Agent 将毕昇工作流当工具调用时，校验可调用的具体 WorkflowVersion。 | AgentVersion 与 WorkflowVersion 的绑定和校验方式。 |

请随回执提供测试 Base URL、OpenAPI 或消息 Schema、鉴权方式、错误码和联调样例。

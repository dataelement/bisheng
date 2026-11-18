# 昆联 Workflow API 使用文档

版本：104环境部署提交 `cbb8bcbee2`；接口合同以当前部署代码为准。

## 交付与安全须知

- 服务地址：`http://110.16.193.170:50055`，业务前缀 `/api/v2/kunlian`。
- 本文覆盖20个业务接口及6个平台侧Key管理接口，每个接口包含认证、入参、出参、HTTP状态、请求/响应示例和限制。
- 测试API Key在独立敏感凭据文件交付；本文不包含真实Key。不要把敏感文件合并进本文、仓库、公开群或浏览器代码。
- 20个业务接口只传必填Query `user_account`，对应毕昇登录账号`user_name`。不传external_tenant_id/external_user_id；账号必须全局精确唯一，并有唯一有效租户关系与现有昆联映射。
- Key验证调用方，user_account指定受信代操作用户；最终权限为Key允许范围/能力与该用户当前业务权限的交集。租户管理员可在自身租户内被代表，全局超级管理员不能被代表。
- 所有业务接口示例中的账号、工作流ID、版本、修订和权限模型均是示意；画布示例只解释JSON结构，不保证可直接发布。创建/保存/发布/授权等写请求应只在获准测试资源上执行。
- 本环境使用HTTP，Bearer在链路上没有TLS保护；只在受控内网使用，不通过不可信网络发送永久Key。正式外部接入建议使用受信HTTPS。
- 客户端不再传Idempotency-Key。每次HTTP为独立操作，重复创建/启动可能产生新资源/运行；不做超时后的盲目重试。内部任务去重、交互原子消费、If-Match和授权修订检查保留。

## 推荐调用顺序

1. 先GET工作流列表确认账号准入；列表为空只能证明请求成功，不能证明对某个工作流有运行或管理权限。
2. 查询当前发布版`/schema`取得输入输出字段；不要把画布`data`当成运行输入。
3. POST启动，记录session_id；轮询原session获取状态、表单和结果；人工输入用对应interaction_id提交。
4. 编辑流程：创建→读取版本详情及draft_revision→If-Match保存→发布指定版本→查询schema→运行。
5. 授权流程：操作人Query用账号，目标Body subject_ref仍用目标昆联OIDC sub；先查当前模型与修订，再提交一次变更。PENDING不等于生效，平台凭operation_ref核对，不提供独立公开回执查询接口。

## 已完成的环境探测与未验项目

平台已使用新签发Key通过网关只读调用：`中数SSO只读测试`、`中数SSO编辑测试`列表HTTP200/业务200，但当前列表为空；不作为工作流执行/授权成功证据。`tong.leisheng`当前有重名记录，返回403/19322，不能用它作为无歧义测试账号。本文不公开全部租户用户目录，实际业务账号与资源由双方确认。

已观察有效Key缺user_account返回401/26001（参数解析失败先走旧认证路径）；有效账号混旧Query或重复账号返回422/19320。这是当前部署的已知错误呈现差异，不代表凭据一定失效；客户端先检查必填参数和身份输入。未知参数/缺Body等须按实际HTTP与业务码同时判断，本文不虚构统一错误格式。

未执行创建/编辑/发布/运行/授权真实写链路；MySQL/DM8竞争、完整节点及附件/多输入输出、权限故障演练仍需独立验收。下面每接口的成功响应为源码合同示例，不是对真实服务逐项调用的实测结果。

## 公共限额与支持范围

默认每Key120请求/60秒；每接入方/租户/实际用户活跃运行5个（跨工作流，含排队/等待/取消中）。超限HTTP429/26074；Retry-After采用当前请求窗口。限额由服务端配置，不接受请求覆盖。

默认排队120秒、执行300秒、人工输入等待900秒、结果查询保留86400秒。到期正式终态payload有界清理，保留服务端内部归属及操作摘要；这些不是无条件完成SLA。

运行协议为至多单个文本表单输入、单个文本输出；支持现有核心LLM/tool/code/condition/普通知识检索节点，但平台Agent/平台知识节点、附件和多输入/输出协议未装配，受理前拒绝。人工输入恢复要求start直接进入输入节点；Code节点等仍受原平台能力开关限制。

## 章节索引

- 01—12、12A：工作流查询、创建、元数据、版本、发布、下线与删除。
- 13—16：运行提交、结果轮询、取消与人工输入。
- 17—20：授权读取、本人权限、授予与撤销。
- 21—26：平台侧Key管理，**不属于持有业务Key的昆联调用方可用权限**。

---



---

# 工作流管理接口（01—12）

> 本章依据正式 route → application → 既有 FlowService／WorkFlowService／仓储的静态代码整理；未连接真实服务。请求示例仅说明协议形状，不保证示例账号具备权限、资源存在或示例画布可发布。资源 ID `workflow-example`、版本 `101` 均为示意值。

## 公共约定

- 示例基地址：`http://110.16.193.170:50055`（按交付指定基地址展示）。
- 所有请求：`Authorization: Bearer <KUNLIAN_API_KEY>`；JSON 写请求使用 `Content-Type: application/json`。Key 仅为占位符。
- 所有接口必填 Query：`user_account`，字符串，长度 1—128，且只能出现一次。本文示例为 `中数SSO编辑测试`，**不表示该账号已取得相应权限**。
- 不接受 Cookie、`x-on-behalf-of`、`x-end-user`、`x-user-id`、`x-tenant-id` 请求头；不接受 `external_tenant_id`、`external_user_id` Query。
- 下文“能力”指 Key capability；“业务权限”指账号对具体工作流的权限，两者均须满足。
- 正常响应统一为 `{"status_code":200,"status_message":"SUCCESS","data":...}`。HTTP 状态与业务 `status_code` 分开判断；创建工作流 HTTP 201，但业务码仍为 200。
- 所有请求体均禁止未定义字段。`?` 表示字段可省略；`null` 是否被忽略取决于各接口，不应统一解释。路径 `workflow_id` 为字符串，未声明 UUID 格式校验；路径 `version_id` 为整数，未声明正数约束。
- 表中的日期时间为 JSON 字符串；底层模型允许日期字段为 null，示例时间不是实际资源数据。

### 公共错误与 HTTP

| 情形 | 实际 HTTP | 响应说明 |
|---|---:|---|
| Key／身份认证失败 | 401 | 认证错误业务码和消息；解析失败也可能优先返回认证错误 |
| Key 能力或业务权限不足 | 403 | 具体错误码依身份／权限拒绝路径而定 |
| 工作流不存在、非本租户或非工作流类型 | 404 | 正式 application 的 NOT_FOUND 路径 |
| 请求模型校验失败，且解析失败的认证回退未先拒绝 | 400 | `{"status_code":400,"status_message":[校验错误...]}`，无 data 字段；不是所有参数缺失均保证返回 400，见下方实测说明 |
| 专门身份依赖判定 INVALID_INPUT，如禁止的身份头／Query | 422 | 错误业务 envelope，区别于普通模型校验 |
| 工作流登记／草稿并发冲突 | 409 | `status_code:10571`，`status_message:"Workflow changed or the registration request conflicts"`，`data:null` |
| 限流 | 429 | 含 Retry-After；具体限额依部署策略 |
| 专门依赖不可用 | 503 | 依实际错误类型返回对应业务码 |

**参数缺失与认证回退的实际边界：**父线程提供的 live 观察记录显示，即使携带有效 `bs-kl` Key，缺少 `user_account` 也返回 **HTTP 401／业务码 26001**，而非 400。代码中模型校验处理会先调用 `_authenticate_parse_failure`，该函数回退到旧 `open_api_access_context` 认证；因此不能承诺“有效昆联 Key 下所有模型错误都返回 400”。缺少请求体等解析／校验失败也可能进入该回退路径，其具体响应须按实际条件判断，本文未将这些情况逐一实测。该 live 结果由父线程提供，本章整理者未另行连接服务。代码路径见[解析失败认证回退](../../src/backend/bisheng/open_api/api/exception_handlers.py#L224-L238)与[校验处理先认证](../../src/backend/bisheng/open_api/api/exception_handlers.py#L254-L283)。

错误示例（草稿冲突）：
```json
{"status_code":10571,"status_message":"Workflow changed or the registration request conflicts","data":null}
```

证据：[统一身份依赖](../../src/backend/bisheng/open_api/application/kunlian_http.py#L99-L128)、[正式错误转换](../../src/backend/bisheng/open_api/application/kunlian_http.py#L38-L90)、[最终 v2 错误处理注册](../../src/backend/bisheng/open_api/api/exception_handlers.py#L165-L221)、[校验处理](../../src/backend/bisheng/open_api/api/exception_handlers.py#L224-L283)、[业务错误 HTTP 映射](../../src/backend/bisheng/open_api/domain/http_status.py#L25-L63)、[正常 envelope](../../src/backend/bisheng/common/schemas/api.py#L9-L27)。

### 公共结构与脱敏边界

**版本摘要 S**：`id:int|null`、`name:string`、`description:string|null`、`is_current:int|null`、`create_time:string|null`、`update_time:string|null`。`is_current` 为整数标记，不是布尔值。

**画布 graph**：存放于工作流／版本响应的 `data.data`，为对象或 null；本章不会把它称作调用输入 schema。响应画布投影只删除已确认的 `nodes[].data.group_params[].params[key="sql_agent"].value.db_password`；不递归删除任意 `password`／`api_key` 业务字段。保存脱敏后的画布时，仅对同一、唯一且身份一致的 Agent 节点恢复被省略的 SQL 密码；显式空值或 null 仍视为调用者编辑。

证据：[版本字段类型](../../src/backend/bisheng/database/models/flow_version.py#L16-L35)、[响应字段白名单及画布投影](../../src/backend/bisheng/workflow/domain/schemas/kunlian_redaction.py#L78-L110)、[SQL 密码处理](../../src/backend/bisheng/workflow/domain/schemas/kunlian_redaction.py#L11-L75)。

## 01 查询工作流列表

**GET `/api/v2/kunlian/workflows`**  
认证：公共 Key 与 user_account；能力 `read`；列表按账号的 `visible` 业务权限过滤。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Query | user_account | string／是 | 公共账号参数 |
| Query | name | string／否 | 名称过滤 |
| Query | cursor | string／否 | 上页 next_cursor；首页省略 |
| Query | page_size | int／否 | 默认 20，范围 1—100 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| data | WorkflowRow[] | 内层数组，不是 envelope 的顶层数组 |
| page_size | int | 本页请求大小 |
| has_more | bool | 是否还有下一页 |
| next_cursor | string\|null | 下一页游标；没有下一页为 null |

WorkflowRow 字段：`id:string`、`name:string`、`description:string|null`、`flow_type:int`（工作流为 10）、`logo:string|null`、`user_id:int|null`、`status:int|null`（1 下线、2 上线）、`create_time:string|null`、`update_time:string|null`、`app_state:null`、`user_name:string|int|null`（查不到用户名时回退 user_id）、`write:bool`、`version_list:列表版本摘要[]`、`tags:透传值`。`tags` 来自旧 TagDao，本文不承诺其内部 shape；客户端宜按可选透传扩展字段处理。

列表版本摘要的真实 DAO 形状：S 加 `flow_id:string`、`data:null`、`user_id:null`、`tenant_id:null`、`flow_type:10`、`is_delete:0`、`original_version_id:null`。后六项为模型默认值；DAO **不查询真实版本 graph／创建人／租户／来源版本**。该结构没有 draft_revision。

### HTTP、示例与限制
正常 HTTP **200**。非法／不匹配的 cursor：HTTP **400**，业务码 **10550**（Invalid pagination cursor）。游标绑定账号、租户、过滤条件和 page_size，改变条件后应从首页重新查询。无 total、items 字段；创建尚未完成的 pending 工作流被过滤。

```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows?user_account=中数SSO编辑测试&page_size=20
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"data":[{"id":"workflow-example","name":"日报","description":null,"flow_type":10,"logo":null,"user_id":12,"status":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T10:00:00","app_state":null,"user_name":"示意用户","write":true,"version_list":[{"id":101,"flow_id":"workflow-example","name":"v1","description":null,"is_current":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T10:00:00","data":null,"user_id":null,"tenant_id":null,"flow_type":10,"is_delete":0,"original_version_id":null}],"tags":[]}],"page_size":20,"has_more":false,"next_cursor":null}}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L100-L109)、[application](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L32-L44)、[游标上下文](../../src/backend/bisheng/api/services/workflow.py#L888-L905)、[封装](../../src/backend/bisheng/api/services/workflow.py#L1042-L1059)、[列表补充字段](../../src/backend/bisheng/api/services/workflow.py#L166-L227)、[真实版本 SELECT](../../src/backend/bisheng/database/models/flow_version.py#L184-L193)、[列表基础列](../../src/backend/bisheng/database/models/flow.py#L757-L768)。

## 02 创建工作流

**POST `/api/v2/kunlian/workflows`**  
认证：公共 Key 与 user_account；能力 `write`。非租户管理员另须满足创建工作流／应用菜单权限，并进行工作流配额检查。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Query | user_account | string／是 | 公共参数 |
| Body | name | string／是 | 长度 1—128 |
| Body | description | string\|null／否 | 默认 null |
| Body | data | object\|null／否 | 编辑画布，默认 null；不是调用输入 schema |
| Body | logo | string\|null／否 | 默认 null |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 新工作流 ID |
| version_id | int | 初始版本 ID |
| name | string | 工作流名称 |

### HTTP、示例与限制
正常 HTTP **201**；body.status_code 为 200。固定创建工作流类型 10、下线状态 1。每次请求由服务端生成内部操作引用，接口未承诺客户端幂等键。创建竞争可返回 10571／409；创建后的 owner 权限投影未完成可返回 10572／503；配额和菜单拒绝按实际业务错误返回。

```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json

{"name":"日报","description":"自动生成日报"}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":"workflow-example","version_id":101,"name":"日报"}}
```
证据：[请求模型](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L20-L28)、[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L112-L120)、[创建权限与返回](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L167-L198)、[创建流程](../../src/backend/bisheng/workflow/application/kunlian_workflow_creation.py#L11-L55)。

## 03 查询工作流详情／编辑画布

**GET `/api/v2/kunlian/workflows/{workflow_id}`**  
认证：公共 Key 与 user_account；能力 `read`；业务 `visible`，for_edit=true 时另须 `edit`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |
| Query | for_edit | bool／否 | 默认 false |

### data 出参
| 字段 | 类型 | 返回条件 |
|---|---|---|
| id、name | string | 两种模式均返回 |
| description、logo | string\|null | 两种模式均返回 |
| status | int\|null | 1 下线、2 上线 |
| versions | {id:int\|null,name:string,is_current:int\|null}[] | 仅默认摘要模式 |
| create_time、update_time | string\|null | 编辑模式 |
| data | object\|null | 仅编辑模式；脱敏画布 |

### HTTP、示例与限制
正常 HTTP **200**；不存在／异租户／非工作流为 **404**；业务权限不足 **403**。默认详情不返回 graph。编辑模式返回工作流当前画布，不是某个版本详情；不自动返回 draft_revision。内部 can_share／kunlian_registration 等字段被正式投影剔除。

```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":"workflow-example","name":"日报","description":null,"status":1,"logo":null,"versions":[{"id":101,"name":"v1","is_current":1}]}}
```
编辑模式请求在 Query 增加 `for_edit=true`，响应形状示例：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":"workflow-example","name":"日报","description":null,"logo":null,"status":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T10:00:00","data":{"nodes":[],"edges":[]}}}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L123-L126)、[application 投影](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L55-L62)、[详情与两种模式](../../src/backend/bisheng/api/services/flow.py#L313-L372)、[白名单](../../src/backend/bisheng/workflow/domain/schemas/kunlian_redaction.py#L78-L110)。

## 04 查询已发布工作流调用 Schema

**GET `/api/v2/kunlian/workflows/{workflow_id}/schema`**  
认证：公共 Key 与 user_account；能力 `read`；业务 `visible`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |
| Query | workflow_version_id | int／否 | 必须 >0；若指定，必须为当前已发布版本 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| workflow_id | string | 工作流 ID |
| workflow_version_id | string | 当前已发布版本 ID；注意是字符串 |
| name、description | string | description 按版本说明→工作流说明→空串回退 |
| input_schema | object | JSON Schema；对象属性为文本字符串，含 required 与 additionalProperties:false |
| output_schema | object | 对象，仅 result:string 为必填属性 |

### HTTP、示例与限制
正常 HTTP **200**。工作流须上线且恰有一个未删除 current 版本；版本须属于当前租户。未上线、指定非当前版本或不支持的图结构：**409／10571**。当前描述器仅支持至多一个文本表单 input、恰一个文本 output；不是任意节点 schema，也不是编辑画布，不返回 graph、dependencies 或 descriptor_digest。

```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/schema?user_account=中数SSO编辑测试&workflow_version_id=101
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"workflow_id":"workflow-example","workflow_version_id":"101","name":"日报","description":"自动生成日报","input_schema":{"type":"object","properties":{"question":{"type":"string"}},"required":["question"],"additionalProperties":false},"output_schema":{"type":"object","properties":{"result":{"type":"string"}},"required":["result"]}}}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L129-L139)、[application](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L46-L53)、[当前发布约束与返回字段](../../src/backend/bisheng/workflow/domain/repositories/kunlian_registration.py#L523-L556)、[Schema 生成规则](../../src/backend/bisheng/workflow/domain/services/kunlian_descriptor.py#L13-L70)。

## 05 更新工作流元数据

**PATCH `/api/v2/kunlian/workflows/{workflow_id}`**  
认证：公共 Key 与 user_account；能力 `write`；业务 `edit`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |
| Body | name | string\|null／否 | 非 null 时长度 1—128 |
| Body | description | string\|null／否 | 仅传入字段参与更新 |
| Body | logo | string\|null／否 | 仅传入字段参与更新 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| id、name | string | 工作流 ID／名称；name 模型不声明可空 |
| description、logo | string\|null | 更新后元数据 |
| status | int\|null | 状态 |
| create_time、update_time | string\|null | 时间 |

### HTTP、示例与限制
正常 HTTP **200**。线上工作流禁止更新，**409／10571**。允许空对象 `{}`；遗漏字段不改，显式 null 会直接赋值，不能理解为忽略。特别是 name 虽请求允许 null，但数据库／模型约束仍可能使该写入失败，不承诺可清空名称。不更新 graph、版本说明或状态。

```http
PATCH http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json

{"name":"新版日报","description":"新描述"}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":"workflow-example","name":"新版日报","description":"新描述","logo":null,"status":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T11:00:00"}}
```
证据：[请求模型](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L31-L34)、[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L142-L147)、[权限](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L64-L71)、[赋值与返回](../../src/backend/bisheng/workflow/domain/repositories/kunlian_workflow_api.py#L50-L67)。

## 06 查询版本列表

**GET `/api/v2/kunlian/workflows/{workflow_id}/versions`**  
认证：公共 Key 与 user_account；能力 `read`；业务 `visible`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数；没有分页参数 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| data | VersionSummary[] | S 结构，可能附加 draft_revision:string |
| total | int | 包含已删除版本的计数，可能大于数组长度 |

VersionSummary 仅允许 S 的字段与 draft_revision；没有 graph、flow_id、user_id、tenant_id、is_delete、original_version_id。draft_revision 由底层管理 scope 分支补充，**不是所有版本列表场景都保证存在**。

### HTTP、示例与限制
正常 HTTP **200**；公共 404／403 规则适用。此接口与 01 的游标分页结构不同：是 `data.data` 数组加 `data.total`，不含 next_cursor。

```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/versions?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"data":[{"id":101,"name":"v1","description":null,"is_current":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T10:00:00"}],"total":1}}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L150-L153)、[字段投影](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L73-L89)、[列表与含删除计数](../../src/backend/bisheng/api/services/flow.py#L53-L81)、[revision 分支](../../src/backend/bisheng/workflow/domain/repositories/kunlian_registration.py#L416-L436)。

## 07 创建版本

**POST `/api/v2/kunlian/workflows/{workflow_id}/versions`**  
认证：公共 Key 与 user_account；能力 `write`；业务 `edit`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |
| Body | name | string／是 | 长度 1—128 |
| Body | description | string\|null／否 | 默认 null |
| Body | data | object\|null／否 | 版本画布，默认 null |
| Body | original_version_id | int\|null／否 | 非 null 必须 >0，须属于本工作流及租户 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| S 的六项字段 | 见公共结构 S | 新版 is_current 默认整数 0 |
| data | object\|null | 脱敏后的版本画布 |

不返回 draft_revision、flow_id、user_id、tenant_id、flow_type、is_delete 或 original_version_id。

### HTTP、示例与限制
正常 HTTP **200**，不是 201。同名版本：**409／10502**。来源版本不存在／越工作流／越租户按 404 路径处理。original_version_id 只存来源 ID，既有创建服务**未据此复制来源画布**；若 data 省略，则新版本 data 为 null。不承诺创建后自动选中或发布。

```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/versions?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json

{"name":"v2","description":"修订版","data":{"nodes":[],"edges":[]},"original_version_id":101}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":102,"name":"v2","description":"修订版","is_current":0,"create_time":"2026-01-01T11:00:00","update_time":"2026-01-01T11:00:00","data":{"nodes":[],"edges":[]}}}
```
空 nodes／edges 仅为画布 shape 示例，不表示可发布。

证据：[请求模型](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L37-L41)、[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L156-L165)、[来源核对与脱敏](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L121-L129)、[创建与同名判断](../../src/backend/bisheng/api/services/flow.py#L221-L259)、[版本默认值](../../src/backend/bisheng/database/models/flow_version.py#L16-L35)。

## 08 查询版本详情

**GET `/api/v2/kunlian/workflows/{workflow_id}/versions/{version_id}`**  
认证：公共 Key 与 user_account；能力 `read`，但业务同时要求 `edit`，底层详情还检查 `visible`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Path | version_id | int／是 | 版本 ID |
| Query | user_account | string／是 | 公共参数 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| S 的六项字段 | 见公共结构 S | 版本元数据 |
| data | object\|null | 脱敏画布 |
| draft_revision | string | 原始草稿摘要，用于保存版本的 If-Match |

不返回 flow_id、user_id、tenant_id、flow_type、original_version_id、is_delete。draft_revision 在本接口明确补充，摘要基于 name、description、原始 data、is_delete，而不是脱敏响应重新计算。

### HTTP、示例与限制
正常 HTTP **200**；跨工作流／跨租户／不存在版本为 **404**；权限不足 **403**。与 04 的调用 schema 完全不同：本接口返回编辑画布。

```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/versions/101?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":101,"name":"v1","description":null,"is_current":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T10:00:00","data":{"nodes":[],"edges":[]},"draft_revision":"<DRAFT_REVISION>"}}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L168-L171)、[核对、权限、字段投影与 revision](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L91-L119)、[底层 visible 检查](../../src/backend/bisheng/api/services/flow.py#L84-L110)、[revision 算法](../../src/backend/bisheng/workflow/domain/repositories/kunlian_registration.py#L33-L34)。

## 09 保存版本草稿

**PUT `/api/v2/kunlian/workflows/{workflow_id}/versions/{version_id}`**  
认证：公共 Key 与 user_account；能力 `write`；业务 `edit`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Path | version_id | int／是 | 版本 ID |
| Query | user_account | string／是 | 公共参数 |
| Header | If-Match | string／业务必需 | 精确使用 08 返回的 draft_revision 原串；不要加 ETag 引号或 W/ 前缀 |
| Body | name | string／是 | 长度 1—128 |
| Body | description | string\|null／否 | null／省略均不更新说明 |
| Body | data | object\|null／否 | null／省略均不更新画布 |
| Body | original_version_id | int\|null／否 | 请求模型接受非 null 正整数，但保存路径不使用此字段 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| S 的六项字段 | 见公共结构 S | 保存后版本元数据 |
| data | object\|null | 保存后脱敏画布 |
| draft_revision | string | 保存后草稿摘要 |

### HTTP、示例与限制
正常 HTTP **200**。If-Match 缺失／不一致，或上线工作流的 current 版本被修改：**409／10571**。非 current 版本不因工作流上线而一律禁止保存。修改 current 版本画布会同步工作流画布。description 的 null 不会清空原说明；此处与 PATCH 元数据不同。画布 `{}` 非 null，会进入画布校验流程，不能当作“保持不变”。

```http
PUT http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/versions/101?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json
If-Match: <DRAFT_REVISION>

{"name":"v1","description":"修订说明","data":{"nodes":[],"edges":[]}}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":101,"name":"v1","description":"修订说明","is_current":1,"create_time":"2026-01-01T10:00:00","update_time":"2026-01-01T11:00:00","data":{"nodes":[],"edges":[]},"draft_revision":"<UPDATED_DRAFT_REVISION>"}}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L174-L185)、[If-Match 读取与返回投影](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L131-L147)、[保存与并发约束](../../src/backend/bisheng/workflow/domain/repositories/kunlian_workflow_api.py#L19-L40)。

## 10 选择当前版本

**POST `/api/v2/kunlian/workflows/{workflow_id}/versions/{version_id}/select`**  
认证：公共 Key 与 user_account；能力 `write`；业务 `edit`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Path | version_id | int／是 | 拟选择版本 |
| Query | user_account | string／是 | 公共参数 |
| Body | — | — | 无定义请求体，不需要 VersionSelection 或 If-Match |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| data（envelope） | null | 不返回版本号、版本对象或工作流对象 |

### HTTP、示例与限制
正常 HTTP **200**，选择已经 current 的版本也返回相同空成功。线上工作流禁止切换：**409／10525**。返回的版本未找到错误 10500 经正式 route 转为 **404**；application 还先核对版本所属工作流与租户。此操作只选择版本，不等于发布。

```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/versions/101/select?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":null}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L188-L191)、[application](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L149-L151)、[线上禁止及空成功](../../src/backend/bisheng/api/services/flow.py#L174-L218)、[返回错误 HTTP 转换](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L61-L85)。

## 11 发布工作流

**POST `/api/v2/kunlian/workflows/{workflow_id}/publish`**  
认证：公共 Key 与 user_account；能力 `publish`；业务 `publish`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |
| Body | version_id | int／是 | >0；拟发布版本 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| data（envelope） | null | 无发布详情对象 |

### HTTP、示例与限制
正常 HTTP **200**。版本须属于该工作流和租户。发布包含图初始化／memory 节点检查，并沿现有平台 Agent／Knowledge 或登记发布路径执行；不是简单改一个状态。普通初始化错误 10526 由 v2 错误映射为 **400**；登记 scope 将初始化失败转换为 **409／10571**。平台依赖还可返回其专门错误，不能将所有发布失败统一写为 409。

```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/publish?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json

{"version_id":101}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":null}
```
证据：[版本选择模型](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L44-L45)、[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L194-L198)、[application](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L153-L165)、[既有发布规则](../../src/backend/bisheng/api/services/workflow.py#L1294-L1382)。

## 12 下线工作流

**POST `/api/v2/kunlian/workflows/{workflow_id}/unpublish`**  
认证：公共 Key 与 user_account；Key 能力仍为 `publish`，但业务权限为 `unpublish`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |
| Body | version_id | int／是 | >0，须为 current 版本 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| data（envelope） | null | 无下线详情对象 |

### HTTP、示例与限制
正常 HTTP **200**。仅允许当前版本下线；指定非 current 版本：**409／10571**。工作流状态设为 1（OFFLINE），不选择另一个版本。本正式接口走窄仓储下线路径，不应根据旧 update_flow_status 的其他分支描述其行为。

```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example/unpublish?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json

{"version_id":101}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":null}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L201-L207)、[独立业务 unpublish 授权与仓储调用](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L153-L163)、[current 检查与状态赋值](../../src/backend/bisheng/workflow/domain/repositories/kunlian_workflow_api.py#L42-L48)。

## 12A 删除工作流

**DELETE `/api/v2/kunlian/workflows/{workflow_id}`**  
认证：公共 Key 与 user_account；Key 能力：`write`；业务权限：`delete`。

### 请求参数
| 位置 | 字段 | 类型／必填 | 说明 |
|---|---|---|---|
| Path | workflow_id | string／是 | 工作流 ID |
| Query | user_account | string／是 | 公共参数 |

### data 出参
| 字段 | 类型 | 说明 |
|---|---|---|
| data（envelope） | null | 无删除详情对象 |

### HTTP、示例与限制
正常 HTTP **200**。仅允许删除未上线或已下线（非 `ONLINE`）的工作流；若工作流处于已上线状态（`ONLINE`），返回 **409／10571**，须先调用 `12 下线工作流` 再删除。工作流不存在、非本租户或非工作流类型返回 **404**；Key 缺少 `write` 能力或账号缺少 `delete` 业务权限返回 **403**。删除操作不可逆，会清理工作流记录、标记版本为已删除，并同步清理权限投影、分组关联资源、访客链接及写入审计日志。

```http
DELETE http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
```
```json
{"status_code":200,"status_message":"SUCCESS","data":null}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L150-L154)、[application](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L200-L216)、[权限投影删除](../../src/backend/bisheng/api/services/flow.py#L499-L537)。


---

# 昆联接口详细说明：运行、权限与 Key 管理（13—26）

## 阅读约定与公共合同

- 服务地址：`http://110.16.193.170:50055`。本文为源代码静态核对，**未连接该地址、未调用真实服务**。
- **全部请求、响应与ID均为示意，不能当作生产数据；`<示意Key，非真实>`等占位符不是有效凭证。** 工作流图决定实际输入名；示例的 `question` 不代表所有工作流都支持此字段。权限模型由接口返回，不能将示例占位符作为固定枚举。
- 成功 envelope：`{"status_code":200,"status_message":"SUCCESS","data":...}`。HTTP 201/202 不改变 envelope 中的 `status_code:200`。
- 表中“可选”表示允许省略；nullable另行标记。所有本文请求 body 模型禁止额外字段。运行提交/交互回答采用严格类型，字符串输入不接受数字强转。
- 13—20 使用业务认证 **A**：`Authorization: Bearer <示意Key，非真实>`，必填单个 Query `user_account`（字符串，1—128字符），示例为 `中数SSO只读测试`。权限仍按该自然人的当前业务权限判断，不因持有Key而绕过。
- 21—26 使用控制面认证 **B**：本地平台登录态，`UserPayload.get_login_user` 加当前全局超管校验；**业务Key不能调用其自身控制面**，不要求 `user_account`。
- 认证A禁止请求头 `cookie`、`x-on-behalf-of`、`x-end-user`、`x-user-id`、`x-tenant-id`；禁止 Query `external_tenant_id` / `external_user_id`、重复 `user_account`。违规为依赖 `INVALID_INPUT`，并非可以额外传入以选租户。
- 正常经昆联Route处理的响应带 `Cache-Control: no-store`。

### 错误与验证必须分层理解

| 来源 | 实际HTTP | 响应合同 |
|---|---:|---|
| `/api/v2` 请求模型/Path/Query验证失败 | 验证mapper为400，但可能先被认证失败覆盖 | 通过parse-failure认证后为 `{"status_code":400,"status_message":[验证错误对象...]}`，**无data**；缺参不能保证必得400 |
| `/api/v1` Key请求模型验证失败 | 200 | 当前全局旧mapper为 `{"status_code":422,"status_message":[验证错误对象...]}`，**无data**；不能据此当业务成功 |
| 昆联依赖/服务 `INVALID_INPUT` | 422 | 业务码19320，data为null；不是以上模型验证响应 |
| RunError / AuthorizationError | 见下表 | `{"status_code":业务码,"status_message":"分类token","data":null}` |
| Key服务 KunlianAccessError | 见Key错误表 | `status_message` 使用owner英文消息，不是分类token |

| Run/权限分类 | HTTP / 业务码 |
|---|---|
| UNAUTHENTICATED | 401 / 26002 |
| SESSION_NOT_FOUND、NOT_FOUND | 404 / 10574 |
| FORBIDDEN | 403 / 10574 |
| UNAVAILABLE | 503 / 10575 |
| INVALID_INPUT | 422 / 19320 |
| 其它分类（如 VERSION_UNAVAILABLE、CONTROL_UNAVAILABLE、INTERACTION_CONSUMED、INPUT_TIMEOUT、REVISION_CONFLICT） | 409 / 10571 |

示意业务错误：
```json
{"status_code":10571,"status_message":"INTERACTION_CONSUMED","data":null}
```

认证A另有Key、身份及目录依赖自身owner错误；限流为 HTTP429 / 26074，并带 `Retry-After`。不能把所有失败都归并成上表的RunError。

**目标环境已知行为（父任务提供的只读验证结果，不是本文作者另发请求）：**在上述104地址，使用有效昆联bs-kl Key但缺少 `user_account` 时实际得到 **HTTP401 / 26001**，并非必然HTTP400。原因链路为v2参数解析失败后先走旧credential verifier，该验证入口不识别bs-kl凭证；其它缺失body等验证失败也可能在parse-failure admission阶段被401覆盖，不应承诺固定400。有效账号同时携带旧参数 `external_tenant_id` / `external_user_id`，以及重复 `user_account`，验证结果均为 **HTTP422 / 19320**。客户端应保证必填Query和Body完整、仅一个user_account、不混用旧身份参数。本任务仅记录现状，不修改认证或异常处理代码。

## 13. 提交运行

**POST** `http://110.16.193.170:50055/api/v2/kunlian/workflow-runs`  
认证：A；Key capability：`invoke`。

| 位置 | 字段 | 必填 | 类型、默认与约束 |
|---|---|---|---|
| Query | user_account | 是 | string，1—128字符 |
| Body | workflow_id | 是 | string，`^[0-9a-f]{32}$` |
| Body | workflow_version_id | 否 | 正整数或null，默认null，最大2^63−1；特别允许1—19位ASCII十进制数字串 |
| Body | input | 否 | object<string,string>，默认 `{}`，实际字段必须符合工作流schema |
| Body | mode | 否 | 仅 `"interactive"` 或null，默认null |

成功HTTP：新建 **202**；内部重放分支200（正式路由每HTTP请求生成新的内部key，不承诺客户端重放）。

| data字段 | 类型 | 出现规则 |
|---|---|---|
| session_id | string | 必有 |
| workflow_id | string | 必有 |
| workflow_version_id | string | 必有，版本ID输出为字符串 |
| status | string | 必有，新受理为QUEUED |

示意请求（Header使用认证A）：
```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflow-runs?user_account=中数SSO只读测试
Content-Type: application/json
Authorization: Bearer <示意Key，非真实>

{"workflow_id":"0123456789abcdef0123456789abcdef","input":{"question":"你好"}}
```
示意响应（HTTP202）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow_id":"0123456789abcdef0123456789abcdef","workflow_version_id":"12","status":"QUEUED"}}
```
注意/错误：必须为可调用的已发布版本并具当前use权限；输入多余key或缺必填字段为INVALID_INPUT；不可用图/版本可报VERSION_UNAVAILABLE；超活跃配额报429。`interactive`必须空input且存在有效表单输入节点。

## 14. 查询运行及结果

**GET** `http://110.16.193.170:50055/api/v2/kunlian/workflow-runs/{session_id}`  
认证：A；capability：`invoke`。

| 位置 | 字段 | 必填 | 类型/说明 |
|---|---|---|---|
| Path | session_id | 是 | string，运行会话ID |
| Query | user_account | 是 | 公共认证A字段 |

成功HTTP：**200**。无请求body。

| data字段 | 类型 | 出现规则 |
|---|---|---|
| session_id | string | 必有 |
| workflow_version_id | string | 必有 |
| status | string | 必有 |
| output | object | 仅SUCCEEDED；正常文本合同为 `{"result":string}` |
| error | string | 仅FAILED |
| interaction_id | string | 仅WAITING_INPUT |
| form | object | 仅WAITING_INPUT，当前输入JSON Schema |
| expires_at | integer | 仅WAITING_INPUT，表单等待截止Unix秒，非结果保留截止 |

状态集：QUEUED、RUNNING、WAITING_INPUT、RESUME_QUEUED、RESUMING、CANCEL_REQUESTED、CANCELLED、SUCCEEDED、FAILED。

示意请求：
```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflow-runs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
```
示意成功响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow_version_id":"12","status":"SUCCEEDED","output":{"result":"你好"}}}
```
示意等待响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow_version_id":"12","status":"WAITING_INPUT","interaction_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","form":{"type":"object","properties":{"question":{"type":"string","pattern":"\\S"}},"required":["question"],"additionalProperties":false},"expires_at":1800000000}}
```
示意运行失败响应（HTTP仍200）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow_version_id":"12","status":"FAILED","error":"INPUT_TIMEOUT"}}
```
注意/错误：他人、跨集成、已失去use权限或过期会话隐藏为404 SESSION_NOT_FOUND。FAILED的error仅暴露QUEUE_TIMEOUT、EXECUTION_TIMEOUT、INPUT_TIMEOUT、RESUME_QUEUE_TIMEOUT、RESUME_EXECUTION_TIMEOUT、EXECUTION_FAILED、INVALID_OUTPUT、FORBIDDEN、RESUME_STATE_INVALID，未知值归一EXECUTION_FAILED。正式接口没有独立`/result`路由；Service.result存在不代表可增加接口。当前query直接返回row.output，不调用Service.result的额外模型验证。

## 15. 取消运行

**POST** `http://110.16.193.170:50055/api/v2/kunlian/workflow-runs/{session_id}/cancel`  
认证：A；capability：`invoke`。

| 位置 | 字段 | 必填 | 类型/说明 |
|---|---|---|---|
| Path | session_id | 是 | string |
| Query | user_account | 是 | 公共认证A字段 |

无请求body。成功HTTP：状态为CANCEL_REQUESTED时 **202**，其它 **200**。

| data字段 | 类型 | 规则 |
|---|---|---|
| session_id | string | 必有 |
| status | string | 当前运行状态 |
| cancel_state | string | CANCEL_REQUESTED→ACCEPTED；CANCELLED→CONFIRMED；其它→ALREADY_TERMINAL |

示意请求：
```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflow-runs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/cancel?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
```
示意响应（HTTP202）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"CANCEL_REQUESTED","cancel_state":"ACCEPTED"}}
```
注意/错误：QUEUED、WAITING_INPUT、RESUME_QUEUED可直接CANCELLED；RUNNING、RESUMING先接受取消；已终态不再改变。超过阶段deadline可能先得到FAILED及ALREADY_TERMINAL。ACCEPTED不等于执行已停止。不可访问会话404，控制材料不可用409 CONTROL_UNAVAILABLE。

## 16. 提交交互答案

**POST** `http://110.16.193.170:50055/api/v2/kunlian/workflow-runs/{session_id}/interactions/{interaction_id}/submit`  
认证：A；capability：`invoke`。

| 位置 | 字段 | 必填 | 类型/说明 |
|---|---|---|---|
| Path | session_id | 是 | string |
| Path | interaction_id | 是 | string，查询返回的交互ID |
| Query | user_account | 是 | 公共认证A字段 |
| Body | input | 是 | object<string,string>，符合当前form |

成功HTTP：首次 **202**；内部同key同答案重放分支200，**不等于正式HTTP重复提交有客户端幂等保障**。

| data字段 | 类型 | 精确规则 |
|---|---|---|
| session_id | string | 必有 |
| interaction_id | string | 必有 |
| status | string | 固定ACCEPTED，这是receipt状态，不是运行状态 |

示意请求：
```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflow-runs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/interactions/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/submit?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
Content-Type: application/json

{"input":{"question":"你好"}}
```
示意响应（HTTP202）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","interaction_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","status":"ACCEPTED"}}
```
注意/错误：receipt没有output、workflow_version_id、operation_ref等额外字段。受理后运行进入RESUME_QUEUED，后续用13—16中的查询接口读取状态。必填字符串strip后不得为空；多余字段/缺字段为INVALID_INPUT；交互不匹配404；已消费409 INTERACTION_CONSUMED；已超时409 INPUT_TIMEOUT。正式每请求新内部key，重复HTTP可能INTERACTION_CONSUMED，不能盲目重试期待200。轮换后的Key可查/取消稳定owner的旧运行，但恢复WAITING_INPUT还重验原credential；原Key吊销后不能借新Key恢复执行。

## 17. 列出工作流授权

**GET** `http://110.16.193.170:50055/api/v2/kunlian/workflows/{workflow_id}/permissions`  
认证：A；capability：`grant`，自然人需manage_permission。

| 位置 | 字段 | 必填 | 类型/默认 |
|---|---|---|---|
| Path | workflow_id | 是 | string |
| Query | user_account | 是 | 公共认证A字段 |
| Query | cursor | 否 | string/null，默认null，opaque游标 |
| Query | limit | 否 | integer，默认50，1—200 |

成功HTTP：**200**。

| data字段 | 类型 | 说明 |
|---|---|---|
| resource_version | integer | 当前资源revision |
| catalog_release_id | integer | 当前权限目录发布ID |
| items | array | 元素见下表 |
| grantable_models | array<{key:string}> | 当前active可授予模型 |
| next_cursor | string/null | 后续页游标 |
| has_more | boolean | 是否继续按游标翻页 |

| items元素字段 | 类型 | 说明 |
|---|---|---|
| assignee_id | string | 授权来源ID |
| assignee_version | integer | 来源版本，撤销时使用 |
| subject | object | 精确为 `{type:string,id:string}` |
| model_key | string | 模型key |
| editable | boolean | 原editable且非protected且subject.type=user |

示意请求：
```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/permissions?user_account=中数SSO只读测试&limit=50
Authorization: Bearer <示意Key，非真实>
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"resource_version":4,"catalog_release_id":2,"items":[{"assignee_id":"27","assignee_version":1,"subject":{"type":"user","id":"9"},"model_key":"<当前模型key示意>","editable":true}],"grantable_models":[{"key":"<当前模型key示意>"}],"next_cursor":null,"has_more":false}}
```
注意/错误：只暴露LOCAL且非继承记录；没有name、protected、page_size、total。过滤后items可少于limit，应遵循has_more/next_cursor。读取前后resource/catalog revision变化报409 REVISION_CONFLICT；投影非CURRENT报503 UNAVAILABLE；无管理权限/不可见为404 NOT_FOUND。不可推断固定模型枚举，正式适配器取当前active模型。

## 18. 查询我的权限

**GET** `http://110.16.193.170:50055/api/v2/kunlian/workflows/{workflow_id}/my-permissions`  
认证：A；capability：`read`，自然人需visible。

| 位置 | 字段 | 必填 | 类型/说明 |
|---|---|---|---|
| Path | workflow_id | 是 | string |
| Query | user_account | 是 | 公共认证A字段 |

无body；成功HTTP：**200**。

| data字段 | 类型 | 说明 |
|---|---|---|
| actions | string[] | 当前实际动作集合，不是固定枚举承诺 |

示意请求：
```http
GET http://110.16.193.170:50055/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/my-permissions?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"actions":["visible","use"]}}
```
注意/错误：没有mode、sources、projection_state字段。projection_degraded不为false拒503 UNAVAILABLE；不可见404 NOT_FOUND。正式权限适配器拒全局超管作为外部业务授权操作者，不可用超管绕过验证。

## 19. 授予权限

**POST** `http://110.16.193.170:50055/api/v2/kunlian/workflows/{workflow_id}/permissions/grants`  
认证：A；capability：`grant`，自然人需manage_permission。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Path | workflow_id | 是 | string |
| Query | user_account | 是 | 公共认证A字段 |
| Body | expected_resource_version | 是 | integer >=0 |
| Body | expected_catalog_release_id | 是 | integer >0 |
| Body | subject_ref | 是 | string，1—128；同身份连接和外部租户中的外部用户ID |
| Body | model_key | 是 | string，1—128；取自当前grantable_models |

成功HTTP：APPLIED为 **200**；PENDING为 **202**。

| data字段 | 类型 | 规则 |
|---|---|---|
| operation_ref | string | durable receipt引用；当前实现为64位SHA256摘要 |
| status | string | APPLIED或PENDING |
| applied_resource_version | integer | 仅内部applied_revision非null时出现；不输出null |

示意请求：
```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/permissions/grants?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
Content-Type: application/json

{"expected_resource_version":4,"expected_catalog_release_id":2,"subject_ref":"external-user-9","model_key":"<17返回的模型key示意>"}
```
示意响应（HTTP200）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"operation_ref":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","status":"APPLIED","applied_resource_version":5}}
```
示意待核对响应（HTTP202）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"operation_ref":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","status":"PENDING"}}
```
注意/错误：只授予当前同租户自然人user，排除global super；subject_ref不是本地user_id，也不是user_account。版本冲突409 REVISION_CONFLICT，成员不存在/模型不可授予/无权限隐藏404 NOT_FOUND。operation_ref是服务端跟踪引用，不是客户端幂等key；**没有正式receipt查询路由**，不可臆造轮询接口。底层outcome FINALIZED才归为APPLIED；未确定结果可PENDING，不可当成已生效。

## 20. 撤销授权

**POST** `http://110.16.193.170:50055/api/v2/kunlian/workflows/{workflow_id}/permissions/grants/{assignee_id}/revoke`  
认证：A；capability：`grant`，自然人需manage_permission。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Path | workflow_id | 是 | string |
| Path | assignee_id | 是 | string，`^[1-9][0-9]{0,18}$` |
| Query | user_account | 是 | 公共认证A字段 |
| Body | expected_resource_version | 是 | integer >=0 |
| Body | expected_catalog_release_id | 是 | integer >0 |
| Body | expected_assignee_version | 是 | integer >=0 |

成功HTTP：APPLIED **200**，PENDING **202**。

| data字段 | 类型 | 规则 |
|---|---|---|
| operation_ref | string | 同19 |
| status | string | APPLIED/PENDING |
| applied_resource_version | integer | 可不出现，不能假设null字段存在 |

示意请求：
```http
POST http://110.16.193.170:50055/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/permissions/grants/27/revoke?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
Content-Type: application/json

{"expected_resource_version":5,"expected_catalog_release_id":2,"expected_assignee_version":1}
```
示意响应（HTTP200）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"operation_ref":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","status":"APPLIED","applied_resource_version":6}}
```
注意/错误：只能撤销直接workflow user grant；受保护、继承、非user等不可变更。版本过期409 REVISION_CONFLICT；不可操作对象可404 NOT_FOUND。PENDING、operation_ref限制同19，不存在额外回执查询接口。

## Key管理公共 KeyItem 与错误

以下字段表供21—26共用；KeyItem不是包装层，不含api_key。

| KeyItem字段 | JSON类型 | 说明 |
|---|---|---|
| id | integer | Key记录ID |
| integration_id | string | 稳定集成身份标识 |
| connection_id | string | 身份连接ID |
| policy_revision | integer | 策略版本，初始1 |
| expires_at | string/null | UTC时间的ISO编码；DB为无时区datetime，不承诺Z后缀 |
| revoked_at | string/null | 吊销时间 |
| created_by | integer | 本地创建者用户ID |
| create_time | string/null | 创建时间 |
| rotated_from_id | integer/null | 来源旧Key ID |
| tenant_ids | string[] | 允许的外部租户ID |
| capabilities | string[] | read/write/publish/invoke/grant的子集 |
| key_mask | string | `bs-kl-********` +末4字符 |

不返回token_hash、last4独立字段、status、name等。只有21、26在KeyItem上额外返回 `api_key:string` 明文一次。

Key服务分类映射：INVALID_INPUT→422/19320；FORBIDDEN→403/19322；NOT_FOUND→404/19322；CONFLICT→409/19327；UNAVAILABLE→503/19324；UNAUTHENTICATED→401/26002。返回data:null，status_message采用owner.Msg，例如：
```json
{"status_code":19327,"status_message":"Identity or tenant mapping conflict. Contact your administrator.","data":null}
```
本地登录/全局超管依赖错误由其owner处理，不保证等同Key服务错误；模型验证遵循开头实际全局mapper区别。

## 21. 签发Key

**POST** `http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys`  
认证：B，本地当前全局超管。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Body | connection_id | 是 | string，1—128 |
| Body | integration_id | 是 | string，1—128 |
| Body | tenant_ids | 是 | string[]，1—1000项 |
| Body | capabilities | 是 | string[]，1—5项，枚举见KeyItem |
| Body | expires_at | 否 | datetime/null，默认null；非null必须未来 |

成功HTTP：**201**。

| data字段 | 类型 | 说明 |
|---|---|---|
| KeyItem全部字段 | 见公共表 | 全部返回 |
| api_key | string | 只此时返回新Key明文，示例为无效占位符 |

示意请求（使用本地登录态，不使用业务Bearer）：
```http
POST http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys
Content-Type: application/json

{"connection_id":"kunlian-main","integration_id":"erp-prod","tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"]}
```
示意响应（HTTP201）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Ab_9","api_key":"<示意Key，非真实，不可使用>"}}
```
注意/错误：connection/integration及scope项均不得空白或含首尾空格，项最长128；列表去重保序；未知capability、过期expiry为服务INVALID_INPUT。aware时间转UTC，naive视UTC。真实Key格式为bs-kl-加43字符随机串，存SHA256不存明文；请安全保存首次明文，不应写入文档/日志。

## 22. 列出Key

**GET** `http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys`  
认证：B。

| 位置 | 字段 | 必填 | 类型/默认 |
|---|---|---|---|
| Query | offset | 否 | integer，默认0，>=0 |
| Query | limit | 否 | integer，默认100，1—100 |

成功HTTP：**200**。无body。

| data | 类型 | 说明 |
|---|---|---|
| 整个data | KeyItem[] | 数组，不是items/total对象，无api_key |

示意请求：
```http
GET http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys?offset=0&limit=100
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":[{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Ab_9"}]}
```
注意/错误：可为空数组；没有total、cursor、has_more。参数验证遵循v1旧mapper；仓库失败服务UNAVAILABLE→503，不返回部分伪成功数据。

## 23. 查询Key详情

**GET** `http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/{key_id}`  
认证：B。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Path | key_id | 是 | integer；服务进一步要求>0 |

成功HTTP：**200**。无body。

| data字段 | 类型 | 说明 |
|---|---|---|
| KeyItem全部字段 | 见公共表 | 无api_key，包括已吊销Key元数据 |

示意请求：
```http
GET http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/1
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Ab_9"}}
```
注意/错误：不是取回密钥的接口；不存在404/19322；key_id<=0为服务INVALID_INPUT→422/19320，非整数是请求验证路径。

## 24. 更新Key范围与有效期

**PATCH** `http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/{key_id}`  
认证：B。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Path | key_id | 是 | integer，服务要求>0 |
| Body | tenant_ids | 否 | string[]/null，数组1—1000项；**显式null服务拒绝** |
| Body | capabilities | 否 | string[]/null，数组1—5项；**显式null服务拒绝** |
| Body | expires_at | 否 | datetime/null；省略不变，null清除expiry，非null必须未来 |

成功HTTP：**200**。

| data字段 | 类型 | 说明 |
|---|---|---|
| KeyItem全部字段 | 见公共表 | 无api_key，policy_revision递增 |

示意请求：
```http
PATCH http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/1
Content-Type: application/json

{"capabilities":["read"],"expires_at":null}
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":2,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read"],"key_mask":"bs-kl-********Ab_9"}}
```
注意/错误：不能更新integration_id/connection_id。`{}`也执行保存并增加revision，不是noop。已吊销Key或乐观锁保存冲突409/19327；不存在404/19322；非法scope/null scope为422/19320。

## 25. 吊销Key

**POST** `http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/{key_id}/revoke`  
认证：B。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Path | key_id | 是 | integer，服务要求>0 |

成功HTTP：**200**。无body。

| data字段 | 类型 | 说明 |
|---|---|---|
| KeyItem全部字段 | 见公共表 | 无api_key；首次写revoked_at并增revision |

示意请求：
```http
POST http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/1/revoke
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":3,"expires_at":null,"revoked_at":"2026-11-16T12:05:00","created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read"],"key_mask":"bs-kl-********Ab_9"}}
```
注意/错误：重复吊销已吊销Key返回现有元数据，不再次增revision；无恢复操作。不存在404/19322；并发保存冲突409/19327；仓库故障503/19324。

## 26. 轮换Key

**POST** `http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/{key_id}/rotate`  
认证：B。

| 位置 | 字段 | 必填 | 类型/约束 |
|---|---|---|---|
| Path | key_id | 是 | integer，服务要求>0 |

成功HTTP：**201**。无body。

| data字段 | 类型 | 说明 |
|---|---|---|
| 新KeyItem全部字段 | 见公共表 | 返回新记录，rotated_from_id指向旧ID，新revision初始1 |
| api_key | string | 新Key明文，仅本次返回 |

示意请求：
```http
POST http://110.16.193.170:50055/api/v1/identity-integrations/kunlian/api-keys/1/rotate
```
示意响应（HTTP201，独立示例：旧Key此时尚未吊销）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":2,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:10:00","rotated_from_id":1,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Cd_8","api_key":"<示意新Key，非真实，不可使用>"}}
```
注意/错误：旧Key原子吊销且旧revision+1，新Key复制connection/integration/tenant/capabilities/expires_at，created_by取本次管理员。旧Key已吊销→409/19327；旧expiry已过去且被复制时_new校验可报422/19320；并发轮换冲突409；不存在404。不能将25的吊销后状态接着用于26的成功示例。

## 运行边界与限制汇总

- 文本输入、文本输出；不接收文件或任意结构化值。interactive必填表单字段要求非空白。
- 已发布图需符合执行边界；目前拒绝platform_agent、platform_knowledge_retriever、fake_output等缺乏独立上下文的节点。不能将“支持已发布图”写成“支持任意图”。
- 会话owner按tenant、稳定integration_id、user隔离；每次重新检查当前身份和use权限。
- 正式配置默认：排队120秒、执行300秒、等待输入900秒、终态保留86400秒、每用户活跃运行5个；均是服务端可配置默认，非固定SLA。
- 请求预算默认每credential共120次/60秒，跨所选tenant/user聚合；Redis分布式固定窗口。Redis故障拒绝受理而不是降级为进程内计数。
- 正式路由每次创建内部uuid操作key；不接受调用方控制operation key。不要用内部重放逻辑承诺HTTP幂等。本文不增加result、receipt查询、events或trace接口。

## 核对依据（静态源代码）

- [正式业务路由](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L216-L332)：运行4、权限4的路径、HTTP及包装。
- [运行DTO](../../src/backend/bisheng/workflow/domain/schemas/kunlian_workflow_invocation.py#L16-L47) 与 [严格合同](../../src/backend/bisheng/workflow/domain/schemas/kunlian_registration.py#L19-L20)。
- [运行应用服务](../../src/backend/bisheng/workflow/application/kunlian_workflow_invocation.py#L91-L188)、[正式运行装配](../../src/backend/bisheng/workflow/application/kunlian_runtime.py#L18-L105)、[交互receipt及取消](../../src/backend/bisheng/workflow/domain/repositories/kunlian_workflow_run.py#L329-L484)。
- [权限shape与receipt](../../src/backend/bisheng/workflow/application/kunlian_workflow_authorization.py#L144-L286)、[正式权限适配](../../src/backend/bisheng/workflow/application/kunlian_permission_api.py#L98-L123)、[持久receipt引用](../../src/backend/bisheng/workflow/domain/repositories/kunlian_grant_receipt.py#L12-L16)。
- [Key路由与body](../../src/backend/bisheng/open_api/api/endpoints/kunlian_credentials.py#L13-L92)、[KeyItem及生命周期](../../src/backend/bisheng/open_api/domain/services/kunlian_credential.py#L104-L302)、[Key模型](../../src/backend/bisheng/open_api/domain/models/kunlian_credential.py#L12-L42)。
- [认证及错误映射](../../src/backend/bisheng/open_api/application/kunlian_http.py#L38-L153)、[v2验证mapper](../../src/backend/bisheng/open_api/api/exception_handlers.py#L254-L283)、[v1验证mapper](../../src/backend/bisheng/main.py#L61-L68)。
- [正式默认限制](../../src/backend/bisheng/core/config/settings.py#L196-L207)、[分布式请求预算](../../src/backend/bisheng/open_api/application/kunlian_limits.py#L23-L55)、[成功envelope](../../src/backend/bisheng/common/schemas/api.py#L9-L27)。

# 工作流管理接口（01—12）

> 本章依据正式 route → application → 既有 FlowService／WorkFlowService／仓储的静态代码整理；未连接真实服务。请求示例仅说明协议形状，不保证示例账号具备权限、资源存在或示例画布可发布。资源 ID `workflow-example`、版本 `101` 均为示意值。

## 公共约定

- 示例基地址：`http://192.168.106.104:3001`（按交付指定基地址展示）。
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows?user_account=中数SSO编辑测试&page_size=20
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows?user_account=中数SSO编辑测试
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example?user_account=中数SSO编辑测试
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/schema?user_account=中数SSO编辑测试&workflow_version_id=101
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
PATCH http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example?user_account=中数SSO编辑测试
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/versions?user_account=中数SSO编辑测试
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/versions?user_account=中数SSO编辑测试
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/versions/101?user_account=中数SSO编辑测试
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
PUT http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/versions/101?user_account=中数SSO编辑测试
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/versions/101/select?user_account=中数SSO编辑测试
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/publish?user_account=中数SSO编辑测试
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows/workflow-example/unpublish?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
Content-Type: application/json

{"version_id":101}
```
```json
{"status_code":200,"status_message":"SUCCESS","data":null}
```
证据：[route](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L201-L207)、[独立业务 unpublish 授权与仓储调用](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L153-L163)、[current 检查与状态赋值](../../src/backend/bisheng/workflow/domain/repositories/kunlian_workflow_api.py#L42-L48)。

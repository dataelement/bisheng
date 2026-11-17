# 昆联接口详细说明：运行、权限与 Key 管理（13—26）

## 阅读约定与公共合同

- 服务地址：`http://192.168.106.104:3001`。本文为源代码静态核对，**未连接该地址、未调用真实服务**。
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

**POST** `http://192.168.106.104:3001/api/v2/kunlian/workflow-runs`  
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflow-runs?user_account=中数SSO只读测试
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

**GET** `http://192.168.106.104:3001/api/v2/kunlian/workflow-runs/{session_id}`  
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflow-runs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?user_account=中数SSO只读测试
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

**POST** `http://192.168.106.104:3001/api/v2/kunlian/workflow-runs/{session_id}/cancel`  
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflow-runs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/cancel?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
```
示意响应（HTTP202）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"session_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"CANCEL_REQUESTED","cancel_state":"ACCEPTED"}}
```
注意/错误：QUEUED、WAITING_INPUT、RESUME_QUEUED可直接CANCELLED；RUNNING、RESUMING先接受取消；已终态不再改变。超过阶段deadline可能先得到FAILED及ALREADY_TERMINAL。ACCEPTED不等于执行已停止。不可访问会话404，控制材料不可用409 CONTROL_UNAVAILABLE。

## 16. 提交交互答案

**POST** `http://192.168.106.104:3001/api/v2/kunlian/workflow-runs/{session_id}/interactions/{interaction_id}/submit`  
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflow-runs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/interactions/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/submit?user_account=中数SSO只读测试
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

**GET** `http://192.168.106.104:3001/api/v2/kunlian/workflows/{workflow_id}/permissions`  
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/permissions?user_account=中数SSO只读测试&limit=50
Authorization: Bearer <示意Key，非真实>
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"resource_version":4,"catalog_release_id":2,"items":[{"assignee_id":"27","assignee_version":1,"subject":{"type":"user","id":"9"},"model_key":"<当前模型key示意>","editable":true}],"grantable_models":[{"key":"<当前模型key示意>"}],"next_cursor":null,"has_more":false}}
```
注意/错误：只暴露LOCAL且非继承记录；没有name、protected、page_size、total。过滤后items可少于limit，应遵循has_more/next_cursor。读取前后resource/catalog revision变化报409 REVISION_CONFLICT；投影非CURRENT报503 UNAVAILABLE；无管理权限/不可见为404 NOT_FOUND。不可推断固定模型枚举，正式适配器取当前active模型。

## 18. 查询我的权限

**GET** `http://192.168.106.104:3001/api/v2/kunlian/workflows/{workflow_id}/my-permissions`  
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
GET http://192.168.106.104:3001/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/my-permissions?user_account=中数SSO只读测试
Authorization: Bearer <示意Key，非真实>
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"actions":["visible","use"]}}
```
注意/错误：没有mode、sources、projection_state字段。projection_degraded不为false拒503 UNAVAILABLE；不可见404 NOT_FOUND。正式权限适配器拒全局超管作为外部业务授权操作者，不可用超管绕过验证。

## 19. 授予权限

**POST** `http://192.168.106.104:3001/api/v2/kunlian/workflows/{workflow_id}/permissions/grants`  
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/permissions/grants?user_account=中数SSO只读测试
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

**POST** `http://192.168.106.104:3001/api/v2/kunlian/workflows/{workflow_id}/permissions/grants/{assignee_id}/revoke`  
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
POST http://192.168.106.104:3001/api/v2/kunlian/workflows/0123456789abcdef0123456789abcdef/permissions/grants/27/revoke?user_account=中数SSO只读测试
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

**POST** `http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys`  
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
POST http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys
Content-Type: application/json

{"connection_id":"kunlian-main","integration_id":"erp-prod","tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"]}
```
示意响应（HTTP201）：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Ab_9","api_key":"<示意Key，非真实，不可使用>"}}
```
注意/错误：connection/integration及scope项均不得空白或含首尾空格，项最长128；列表去重保序；未知capability、过期expiry为服务INVALID_INPUT。aware时间转UTC，naive视UTC。真实Key格式为bs-kl-加43字符随机串，存SHA256不存明文；请安全保存首次明文，不应写入文档/日志。

## 22. 列出Key

**GET** `http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys`  
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
GET http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys?offset=0&limit=100
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":[{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Ab_9"}]}
```
注意/错误：可为空数组；没有total、cursor、has_more。参数验证遵循v1旧mapper；仓库失败服务UNAVAILABLE→503，不返回部分伪成功数据。

## 23. 查询Key详情

**GET** `http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/{key_id}`  
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
GET http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/1
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":1,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read","invoke"],"key_mask":"bs-kl-********Ab_9"}}
```
注意/错误：不是取回密钥的接口；不存在404/19322；key_id<=0为服务INVALID_INPUT→422/19320，非整数是请求验证路径。

## 24. 更新Key范围与有效期

**PATCH** `http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/{key_id}`  
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
PATCH http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/1
Content-Type: application/json

{"capabilities":["read"],"expires_at":null}
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":2,"expires_at":null,"revoked_at":null,"created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read"],"key_mask":"bs-kl-********Ab_9"}}
```
注意/错误：不能更新integration_id/connection_id。`{}`也执行保存并增加revision，不是noop。已吊销Key或乐观锁保存冲突409/19327；不存在404/19322；非法scope/null scope为422/19320。

## 25. 吊销Key

**POST** `http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/{key_id}/revoke`  
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
POST http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/1/revoke
```
示意响应：
```json
{"status_code":200,"status_message":"SUCCESS","data":{"id":1,"integration_id":"erp-prod","connection_id":"kunlian-main","policy_revision":3,"expires_at":null,"revoked_at":"2026-11-16T12:05:00","created_by":2,"create_time":"2026-11-16T12:00:00","rotated_from_id":null,"tenant_ids":["external-tenant-1"],"capabilities":["read"],"key_mask":"bs-kl-********Ab_9"}}
```
注意/错误：重复吊销已吊销Key返回现有元数据，不再次增revision；无恢复操作。不存在404/19322；并发保存冲突409/19327；仓库故障503/19324。

## 26. 轮换Key

**POST** `http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/{key_id}/rotate`  
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
POST http://192.168.106.104:3001/api/v1/identity-integrations/kunlian/api-keys/1/rotate
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

# 昆联 Workflow 开放接口调用说明

> 实施中接口合同；尚未部署或真实联调。真实支持边界与证据见 [verification.md](./verification.md)。API Key 仅放服务端，禁止发给浏览器。

## 1. 调用格式

所有业务接口使用 `/api/v2/kunlian` 前缀：

```http
Authorization: Bearer <API_KEY>
```

所有业务请求均在 Query 提供唯一的操作人身份参数：

- `user_account`：必填，1～128字符，不接受空白或首尾空格；精确匹配毕昇登录账号 `user_name`，大小写不自动折叠；不是显示姓名、毕昇用户ID、成员ID或昆联 OIDC `sub`。旧 `external_tenant_id` / `external_user_id` Query 已移除，单独或混合传入均拒绝，不会被当成租户切换参数。

不再要求调用方提供 `external_tenant_id` / `external_user_id`。服务端按账号定位用户，并从有效成员关系唯一解析租户；无法唯一解析时拒绝，不允许调用方指定租户或回退默认租户。服务端仍验证Key绑定的可信连接、用户/租户映射及有效资格，并核对解析出的外部租户是否在Key的 `tenant_ids` 允许范围内，按实际用户权限操作；账号查询不意味着放开所有租户。不能混用Cookie、X-On-Behalf-Of、X-End-User或伪造本地身份参数。读与写统一传Query身份，JSON只承载业务数据。

返回统一包含 `status_code`、`status_message`、`data`。注意HTTP状态与五位业务错误码是不同字段。所有响应不缓存。

## 1.1 全部 26 个接口对照表

以下按当前路由、请求模型和业务校验整理，**每行是一个独立的 HTTP 方法＋完整路径**，共20个业务接口、6个Key管理接口。路径不含域名，不需要再拼接前缀。接口已在代码中注册，但尚未部署、未完成真实环境验收。

### 公共必填项与表格约定

- **业务公共必填（适用于01～20每一行）**：Header `Authorization: Bearer <API_KEY>`；Query `user_account`（非空，精确匹配毕昇 `user_name`）。租户由服务端从有效成员关系唯一解析，并继续校验内部映射和Key外部租户范围，不由Query传入。下表“必填参数”列列出这些公共项之外的全部必填项。
- **管理公共认证（适用于21～26每一行）**：毕昇本地全局超级管理员的有效登录态，并实时复核资格；不是昆联API Key，不传业务Query身份参数。具体会话凭据沿用现有平台登录机制。
- `Path`＝URL路径参数，`Query`＝URL查询参数，`Header`＝请求头，`Body`＝JSON请求体。含Body的请求使用 `Content-Type: application/json`。
- “Body必需、字段均可选”表示必须发送JSON对象（可为 `{}`），并不意味着每个字段都必填。表中可选字段、分页默认值均以当前代码为准；不把可选字段伪写成必填。
- 五个写操作（创建工作流、启动运行、提交答案、授予授权、撤销授权）不要求客户端传递幂等键。服务端每次HTTP请求自动生成内部操作ID，用于worker投递、状态跟踪和权限投影；重复HTTP请求不承诺查回先前操作或避免再次受理，调用方不得据此安全重试。
- Header `If-Match` 是保存版本的**业务必填校验**，虽然不在FastAPI函数签名里声明必填，缺少或过期仍会返回409。其值取编辑版本详情返回的 `draft_revision`，不能自行生成；本次幂等策略调整不改变该校验。
- 授权操作的资源/授权revision校验保持不变，仍须使用权限查询返回的版本值；本次调整不改变revision语义。

### A. Workflow 查询、编辑与发布（01～12）

**每行均须携带上述业务公共必填项。** Key能力只控制可调用接口；实际用户还须满足对应业务权限与创建资格。

| 编号 | HTTP方法 | 完整路径 | 必填参数（公共项之外） | 可选参数 / 默认值 | Key能力 | 用途与关键约束 |
|---|---|---|---|---|---|---|
| 01 | GET | `/api/v2/kunlian/workflows` | 无 | Query：`name`、`cursor`；`page_size=20`，范围1～100 | `read` | 查询实际用户可见工作流，返回游标分页结果。 |
| 02 | POST | `/api/v2/kunlian/workflows` | Body：`name`（1～128字符） | Body：`description`、`data`、`logo` | `write` | 创建工作流；用户须有创建资格并满足配额。所属租户、创建人固定为可信映射身份；服务端自动生成内部操作ID。 |
| 03 | GET | `/api/v2/kunlian/workflows/{workflow_id}` | Path：`workflow_id` | Query：`for_edit=false` | `read` | 查询详情；普通详情不返回编辑图，`for_edit=true`需编辑资格。 |
| 04 | PATCH | `/api/v2/kunlian/workflows/{workflow_id}` | Path：`workflow_id`；Body对象必需，字段均可选 | Body：`name`（提供时1～128字符）、`description`、`logo` | `write` | 修改元数据；不能传`status`、身份或画布字段；在线工作流拒绝直接修改。 |
| 05 | GET | `/api/v2/kunlian/workflows/{workflow_id}/schema` | Path：`workflow_id` | Query：`workflow_version_id`（正整数） | `read` | 查询当前有效发布版的输入输出定义，不返回编辑图；显式版本必须匹配当前发布版。 |
| 06 | GET | `/api/v2/kunlian/workflows/{workflow_id}/versions` | Path：`workflow_id` | 无 | `read` | 查询版本元数据列表，不返回完整编辑图。 |
| 07 | POST | `/api/v2/kunlian/workflows/{workflow_id}/versions` | Path：`workflow_id`；Body：`name`（1～128字符） | Body：`description`、`data`、`original_version_id`（正整数） | `write` | 创建新版本；来源版本如提供，必须属于本工作流及本租户。来源标识本身不表示服务端一定复制来源画布。 |
| 08 | GET | `/api/v2/kunlian/workflows/{workflow_id}/versions/{version_id}` | Path：`workflow_id`、`version_id`（整数） | 无 | `read` | 查询指定版本详情、脱敏编辑图与`draft_revision`；实际用户必须有`edit`权限。 |
| 09 | PUT | `/api/v2/kunlian/workflows/{workflow_id}/versions/{version_id}` | Path：`workflow_id`、`version_id`；Header：`If-Match`；Body：`name`（1～128字符） | Body：`description`、`data`、`original_version_id` | `write` | 保存版本；按修订拒绝陈旧写入，保护当前在线版本。`original_version_id`不是此接口修改版本来源的手段。 |
| 10 | POST | `/api/v2/kunlian/workflows/{workflow_id}/versions/{version_id}/select` | Path：`workflow_id`、`version_id` | 无；不需要Body | `write` | 选择编辑版本，沿用现有切换校验；不等于发布。 |
| 11 | POST | `/api/v2/kunlian/workflows/{workflow_id}/publish` | Path：`workflow_id`；Body：`version_id`（正整数） | 无 | `publish` | 校验并发布指定版本，仍需实际用户发布权限。 |
| 12 | POST | `/api/v2/kunlian/workflows/{workflow_id}/unpublish` | Path：`workflow_id`；Body：`version_id`（正整数） | 无 | `publish` | 下线当前版本；旧版本请求不能误下线新版本，仍需实际用户下线权限。 |

### B. 运行与人工输入（13～16）

**每行均须携带上述业务公共必填项。** 查询、取消、答案提交都必须满足运行归属及当前资格，不能通过修改用户参数接管其他人的运行。

| 编号 | HTTP方法 | 完整路径 | 必填参数（公共项之外） | 可选参数 / 默认值 | Key能力 | 用途与关键约束 |
|---|---|---|---|---|---|---|
| 13 | POST | `/api/v2/kunlian/workflow-runs` | Body：`workflow_id`（32位小写十六进制标识） | Body：`workflow_version_id`（正整数或十进制字符串）、`input={}`（字符串到字符串的对象）、`mode="interactive"` | `invoke` | 启动工作流；省略版本时选当前有效发布版。服务端自动生成内部操作ID；重复HTTP不承诺查回或去重；交互模式首次输入必须为空。 |
| 14 | GET | `/api/v2/kunlian/workflow-runs/{session_id}` | Path：`session_id`（启动返回的运行标识） | 无 | `invoke` | 查询状态，成功带`output`，失败带安全`error`，等待输入带`interaction_id`、`form`、`expires_at`。 |
| 15 | POST | `/api/v2/kunlian/workflow-runs/{session_id}/cancel` | Path：`session_id` | 无；不需要Body或幂等键 | `invoke` | 幂等请求取消；返回`cancel_state`，区分受理、确认和原有终态；不承诺回滚外部副作用。 |
| 16 | POST | `/api/v2/kunlian/workflow-runs/{session_id}/interactions/{interaction_id}/submit` | Path：`session_id`、`interaction_id`；Body：`input`（字符串到字符串的对象） | 无 | `invoke` | 提交等待表单的答案，字段按原表单Schema验证，恢复同一运行；服务端自动生成内部操作ID，重复HTTP不承诺查回或避免再次提交；`input`无缺省值，不能省略。 |

### C. 工作流授权（17～20）

**每行均须携带上述业务公共必填项。** Query中的 `user_account` 是操作人的毕昇账号；Body中的 `subject_ref` 仍是被授权用户的昆联 OIDC `sub`，不是操作人账号，二者含义和取值协议不同。

| 编号 | HTTP方法 | 完整路径 | 必填参数（公共项之外） | 可选参数 / 默认值 | Key能力 | 用途与关键约束 |
|---|---|---|---|---|---|---|
| 17 | GET | `/api/v2/kunlian/workflows/{workflow_id}/permissions` | Path：`workflow_id` | Query：`cursor`；`limit=50`，范围1～200 | `grant` | 查询可管理授权记录、修订和可授予模型；操作人须有授权管理资格。 |
| 18 | GET | `/api/v2/kunlian/workflows/{workflow_id}/my-permissions` | Path：`workflow_id` | 无 | `read` | 查询本次实际用户对工作流的有效动作权限，不修改授权。 |
| 19 | POST | `/api/v2/kunlian/workflows/{workflow_id}/permissions/grants` | Path：`workflow_id`；Body：`expected_resource_version`（≥0）、`expected_catalog_release_id`（>0）、`subject_ref`、`model_key`（均1～128字符） | 无 | `grant` | 给同租户有效已映射用户授予当前允许模型；服务端自动生成内部操作ID；授权revision取权限查询结果；PENDING为202，APPLIED为200。 |
| 20 | POST | `/api/v2/kunlian/workflows/{workflow_id}/permissions/grants/{assignee_id}/revoke` | Path：`workflow_id`、`assignee_id`（无前导零的正整数字符串，1～19位）；Body：`expected_resource_version`（≥0）、`expected_catalog_release_id`（>0）、`expected_assignee_version`（≥0） | 无 | `grant` | 撤销指定直接授权记录，不是按用户ID撤销全部权限；服务端自动生成内部操作ID；保护/继承来源不可修改。 |

### D. API Key 管理（21～26）

**每行均须使用上述管理公共认证**，不使用业务Bearer Key，不要求业务Query `user_account`。完整路径已包含`/api/v1`。

| 编号 | HTTP方法 | 完整路径 | 必填参数（管理认证之外） | 可选参数 / 默认值 | 用途与关键约束 |
|---|---|---|---|---|---|
| 21 | POST | `/api/v1/identity-integrations/kunlian/api-keys` | Body：`connection_id`、`integration_id`（各1～128字符）、`tenant_ids`（非空数组，最多1000项）、`capabilities`（非空数组，最多5项） | Body：`expires_at`（日期时间；省略或null表示不设到期） | 签发Key并配置允许的外部租户和能力；明文仅本次响应显示。标识须非空且无首尾空格，能力取`read/write/publish/invoke/grant`。 |
| 22 | GET | `/api/v1/identity-integrations/kunlian/api-keys` | 无 | Query：`offset=0`（≥0）、`limit=100`（1～100） | 查询Key元数据列表，仅返回遮罩，不取回原明文。 |
| 23 | GET | `/api/v1/identity-integrations/kunlian/api-keys/{key_id}` | Path：`key_id`（正整数） | 无 | 查询单个Key元数据、允许范围和状态，不返回哈希或明文。 |
| 24 | PATCH | `/api/v1/identity-integrations/kunlian/api-keys/{key_id}` | Path：`key_id`；Body对象必需，字段均可选 | Body：`tenant_ids`、`capabilities`、`expires_at`；省略字段保持原值 | 修改允许范围与到期；`tenant_ids`/`capabilities`如提供须非空且不能为null，`expires_at:null`明确清除到期限制，已撤销Key不能借此恢复。 |
| 25 | POST | `/api/v1/identity-integrations/kunlian/api-keys/{key_id}/revoke` | Path：`key_id` | 无；不需要Body | 撤销Key，重复撤销保持幂等；撤销后不能发起新的业务操作。 |
| 26 | POST | `/api/v1/identity-integrations/kunlian/api-keys/{key_id}/rotate` | Path：`key_id` | 无；不需要Body | 同事务撤销原Key并签发继承范围的新Key；新明文只在本次显示，稳定接入方标识不变。 |

### 参数易混淆说明

- `workflow_id`是工作流标识；`version_id`是路径/发布Body中的版本标识；`workflow_version_id`用于Schema查询和运行启动，二者命名与实际接口保持一致。
- `session_id`是一次运行，不是工作流ID；`interaction_id`来自该运行的等待表单；`assignee_id`来自授权查询的授权记录，不是用户ID。
- 创建版本与保存版本都要求Body `name`，即便只想修改画布也不能省略；启动的`input`可省略，提交人工答案的`input`不能省略。
- 02、13、16、19、20均由服务端自动生成内部操作ID，不再要求客户端提供`Idempotency-Key`；09仍要求`If-Match`。版本创建本身也没有幂等键合同，重复HTTP不承诺查回或去重。
- 下表之后保留分组简表、调用示例、响应和运行限制，便于实际接入时查阅。

## 2. 查询与管理

| 方法 | 路径 | Key能力 |
|---|---|---|
| GET | `/workflows` | read |
| POST | `/workflows` | write |
| GET / PATCH | `/workflows/{workflow_id}` | read / write |
| GET / POST | `/workflows/{workflow_id}/versions` | read / write |
| GET | `/workflows/{workflow_id}/schema` | read |
| GET / PUT | `/workflows/{workflow_id}/versions/{version_id}` | read / write |
| POST | `/workflows/{workflow_id}/versions/{version_id}/select` | write |
| POST | `/workflows/{workflow_id}/publish` | publish |
| POST | `/workflows/{workflow_id}/unpublish` | publish |

`GET /workflows/{workflow_id}/schema` 使用可选 `workflow_version_id` 查询当前发布版的输入输出定义，只返回Schema与必要元数据，无需读取编辑图；显式版本必须匹配当前发布版。

列表使用cursor/page_size（1–100）分页。普通详情与版本列表不返回编辑图，单版本图需要实际用户edit资格；仅Key含read能力不构成编辑图访问资格。已证实的SQL Agent数据库密码字段不会返回。

创建示例：

```http
POST /api/v2/kunlian/workflows?user_account=kunlian_user
Authorization: Bearer <API_KEY>
Content-Type: application/json

{"name":"昆联测试工作流","description":"业务说明"}
```

身份与创建人/租户由服务端固定，不能在JSON设置user_id、tenant_id、status、flow_type。

版本创建/保存JSON包括name、description、data和可选original_version_id；原版本必须属于当前工作流及租户。保存必须携带详情/列表返回的 `draft_revision` 作为 `If-Match`，过期修订返回409，不能盲目重试覆盖。

发布与下线JSON均为：

```json
{"version_id":123}
```

下线必须匹配当前版本，迟到的旧版本下线请求不能下线新版本。选择编辑版本不等于发布。首批不开放工作流或版本删除。

## 3. 运行

| 方法 | 路径 | Key能力 |
|---|---|---|
| POST | `/workflow-runs` | invoke |
| GET | `/workflow-runs/{session_id}` | invoke |
| POST | `/workflow-runs/{session_id}/cancel` | invoke |
| POST | `/workflow-runs/{session_id}/interactions/{interaction_id}/submit` | invoke |

启动示例（同样携带操作人账号Query与Bearer）：

```http
POST /api/v2/kunlian/workflow-runs?user_account=kunlian_user
Authorization: Bearer <API_KEY>
Content-Type: application/json

{"workflow_id":"32位工作流ID","input":{"question":"你好"}}
```

`workflow_version_id` 可省略，首次受理选择当前有效发布版；指定时必须是当前可用版本。新受理202；服务端为本次HTTP自动生成内部操作ID，重复HTTP不承诺查回先前受理或避免再次启动。受理后固定版本，发布变化不替换原运行。

交互启动示例：

```json
{"workflow_id":"32位工作流ID","mode":"interactive","input":{}}
```

轮询WAITING_INPUT取得interaction_id/form/expires_at，再提交答案：

```http
Content-Type: application/json

{"input":{"question":"人工填写内容"}}
```

取消202表示受理，200表示已终结；响应cancel_state分别为ACCEPTED（取消已受理）、CONFIRMED（已确认取消）、ALREADY_TERMINAL（已有终态）。轮询status确认最终状态。运行失败只返回稳定错误分类，不返回原始异常文本。不承诺回滚已发生的外部副作用。

### 当前运行协议限制

- 支持单个文本表单输入、单个文本输出，使用已有核心Workflow引擎及LLM/tool/code/condition/普通知识检索节点。
- 人工输入恢复要求start直接进入该输入节点，其后可执行核心图。
- 平台Agent/平台知识节点、多输入/多输出、附件及非文本输入输出目前明确拒绝，不会受理后降级假成功。
- Key轮换后，同一接入方且用户/租户资格仍满足的新Key可查询或取消旧运行。旧Key撤销后不再恢复其等待运行；轮换不复活已经终结的运行。不能以新Key提交答案成功等同于可恢复旧执行。

## 4. 授权

| 方法 | 路径 | Key能力 |
|---|---|---|
| GET | `/workflows/{workflow_id}/permissions` | grant |
| GET | `/workflows/{workflow_id}/my-permissions` | read |
| POST | `/workflows/{workflow_id}/permissions/grants` | grant |
| POST | `/workflows/{workflow_id}/permissions/grants/{assignee_id}/revoke` | grant |

授予JSON：

```json
{
  "expected_resource_version":10,
  "expected_catalog_release_id":1,
  "subject_ref":"目标昆联用户sub",
  "model_key":"查询到的当前可授予模型key"
}
```

不要求客户端提供幂等键；服务端为每次HTTP自动生成内部操作ID，并保留worker、状态和权限投影机制。版本值来自权限查询，不能伪造。权限模型沿用平台当前可授予集合，操作人还须具备工作流授权管理权限。目标必须是本外部租户内有效已映射用户。

撤销JSON：

```json
{"expected_resource_version":10,"expected_catalog_release_id":1,"expected_assignee_version":2}
```

只能修改允许编辑的本地直接用户授权，不能修改保护/继承来源或转移所有者。撤销单条授权不代表最终有效权限必然消失。返回PENDING使用HTTP202，最终APPLIED使用200；重复HTTP不承诺查回先前操作。授权PENDING只能凭响应中的`operation_ref`由平台核对F048 ledger及投影状态，不能在同一请求中查回，也不能换新请求盲目重复写。SQL回执已claim而权限ledger尚未创建时崩溃，可能持续PENDING，需平台受控核对。

## 5. Key管理

控制面为 `/api/v1/identity-integrations/kunlian/api-keys`，仅毕昇本地全局超级管理员会话可调用；业务Key不能管理自身。

- POST签发：connection_id、integration_id、tenant_ids、capabilities、可选expires_at。
- GET列表、GET `/{key_id}`详情：只返回遮罩，不能取回原Key。
- PATCH `/{key_id}`修改允许范围与到期。
- POST `/{key_id}/revoke`撤销。
- POST `/{key_id}/rotate`轮换，原Key撤销，新Key仅本次显示。

capabilities为read/write/publish/invoke/grant。integration_id是平台维护的稳定接入方标识，不应为不同可信连接复用。`tenant_ids` 仍是Key允许的外部租户范围，不是毕昇本地租户ID；改用账号Query不删除该范围校验，也不允许所有租户。新租户/用户同步不会自动扩大Key范围。

## 6. 联调前置与验收

需先完成可信目录同步、外部租户映射、有效用户及成员投影；不因传了用户参数自动开户。用普通用户验证可见、运行与编辑权限，再用租户管理员验证本租户管理；全局超管始终禁止作为被代表用户。

默认服务端 `workflow.kunlian_api`：请求每Key120次/60秒（跨租户汇总），排队120秒、执行300秒、人工输入等待900秒、结果查询保留86400秒。请求超限HTTP429/业务码26074，Retry-After为当前窗口；这些是可调服务端策略，不接受请求参数覆盖。请求限流使用Redis原子脚本，依赖故障拒绝；`max_active_per_user`默认5，按接入方/租户/实际用户跨工作流限制活跃运行（含排队、等待输入和取消中），以User行锁串行化新受理，超限同样429/26074。仅服务端内部任务重放保护不占新额度；重复HTTP不承诺查回或去重，若因此新建运行则按新运行计入请求和活跃额度。实际双库锁竞争仍待验证。到期正式终态的结果、图和输入通过有界清理任务清除；服务端内部操作记录按保留策略清理，客户端不持有或复用旧幂等键。每任务最多100条；无正式标记的旧记录不会误清。

当前仅本地测试，无部署、真实凭据或真实业务数据变更。正式环境需执行模型建表/升级、权限运行时与Worker/Beat装配验证、Python3.11及MySQL/DM8测试，具体结果不得以本地SQLite或Python3.14测试替代。

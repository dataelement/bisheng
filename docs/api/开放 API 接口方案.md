# BiSheng 开放 API 接口方案

---

## 1. 概述

### 1.1 能力总览

| 能力 | 说明 | 章节 |
|---|---|---|
| **知识库** | 知识资源的创建与管理、文档上传与解析、语义检索、元数据管理、问答对管理、引用溯源 | [第 3 章](#3-知识库接口) |
| **工作流** | 触发已发布的工作流执行，支持流式输出与多轮人机交互 | [第 4 章](#4-工作流接口) |
| **助手** | 以 OpenAI 兼容格式调用智能助手对话 | [第 5 章](#5-助手接口) |
| **会话记录** | 查询会话历史、生成会话标题、写入用户反馈、回填外部消息 | [第 6 章](#6-会话记录接口) |

### 1.2 接入流程

```
① 申请密钥              ② 选择身份模式            ③ 调用接口
管理员创建服务账号     →  按你的用户体系选择     →  携带密钥与身份头
签发密钥并勾选权限位      两种模式之一               发起 HTTP 请求
并授予所需资源
```

### 1.3 典型集成场景

按两个问题即可确定应选的模式：**这次调用背后有终端用户吗？如果有，他们在 BiSheng 上有账号吗？**

| 场景 | 你的应用长什么样 | 应选身份模式 |
|---|---|---|
| **系统集成** | 后台任务、数据管道，没有终端用户的概念。例如每天把 ERP 的新合同同步进知识库，或订单状态变更时触发审批工作流 | 服务账号模式 |
| **企业内部应用** | 自建门户或业务系统，使用者就是 BiSheng 平台上的用户。例如员工在自建系统里搜索知识库，结果需与其在 BiSheng 中看到的一致 | 代表平台用户模式 |
| **对外应用** | 面向自己客户或公众的应用，使用者与 BiSheng 无账号关系。例如对外客服机器人 | 服务账号模式<br>+ 外部用户标识头 |

系统集成与对外应用走的是**同一条技术路径**（权限基准都是服务账号），差别只在两处：对外应用需要按终端用户分区会话，以及服务账号的授权尺度截然不同——请见 §2.3.1。

---

## 2. 接入准备

### 2.1 基础信息

| 项 | 值 |
|---|---|
| 接口根地址 | `https://<你的部署域名>/api/v2` |
| 请求/响应格式 | JSON（文件上传接口为 `multipart/form-data`） |
| 字符编码 | UTF-8 |
| 时间格式 | `YYYY-MM-DD HH:mm:ss`（除特别注明为 Unix 时间戳的字段） |

本文档中所有接口路径均为相对于接口根地址的路径。例如 `POST /filelib/retrieve` 的完整地址是 `https://<你的部署域名>/api/v2/filelib/retrieve`。

### 2.2 认证

所有接口均需在请求头携带 API 密钥，**无密钥一律返回 401**：

```
Authorization: Bearer <API_KEY>
```

#### 密钥与服务账号

密钥统一以 `bs-sak-` 为前缀，由管理员签发给一个**服务账号**。

服务账号是专用于系统集成的主体：它不能登录平台，权限由管理员单独授予，不继承任何自然人。这意味着——

- 集成的权限边界可以按最小必要收敛，不会因为借用了某位员工的账号而过宽；
- 不会因为某位员工离职或账号变动导致集成中断；
- 审计记录能明确追溯到具体是哪个系统发起的调用。

一个集成建议对应一个服务账号，便于独立授权、独立停用与独立审计。

#### 权限位

创建密钥时按需勾选，**默认一个都不勾**。调用未被授予权限位的接口返回 `26003`，错误信息会指明缺少哪一位。

| 权限位 | 授予的能力 |
|---|---|
| `knowledge:read` | 知识资源列表、检索、文件列表、元数据读取、问答对查询、引用溯源查询 |
| `knowledge:write` | 知识资源增删改、文件上传删除、元数据写入、问答对增删改 |
| `workflow:invoke` | 触发与停止工作流 |
| `workflow:read` | 查询工作流信息 |
| `assistant:invoke` | 助手对话 |
| `assistant:read` | 助手信息与列表查询 |
| `session:read` | 会话历史查询、生成会话标题 |
| `session:write` | 会话反馈写入（点赞、标记已解决、评论） |
| `session:sync` | 向已有会话回填消息 |
| `delegate` | 代表平台用户执行（见 §2.3.2） |

> **为什么 `session:sync` 单独成位**：回填接口可以向会话写入任意消息，等同于改写对话记录；而反馈类操作只改元数据。风险量级不同的动作不共用权限位，因此想收集用户点赞的集成不会连带获得改写历史的能力。

#### 两层授权：权限位 × 资源授权

一次调用能不能成功，由**两层"与"关系**共同决定。两层由管理员在**不同的界面**配置，排障时请分清：

| 层 | 判定什么 | 在哪配置 | 不满足时 |
|---|---|---|---|
| **① 密钥权限位** | 这把密钥能做哪**一类**动作（读知识库 / 调工作流 / 委托……） | 密钥的创建或编辑表单 | `26003`，并指明缺哪一位 |
| **② 主体资源授权** | 执行身份对**这一个具体资源**有什么权限 | 服务账号详情页的「资源授权」 | 各业务模块自身的资源权限错误 |

两层缺一不可：持有 `knowledge:read` 但服务账号未被授予知识库 A，读 A 失败；被授予了 A 但密钥没勾 `knowledge:read`，同样失败。

**两种失败返回不同的错误码**，据此即可判断该找管理员补权限位，还是该申请资源授权。

> 使用**代表平台用户模式**时，第二层的判定基准整个换成被代表用户，服务账号自身的资源授权此刻不参与判定。详见 §2.3.2。

#### 安全须知

- 密钥明文仅在创建时展示一次，请妥善保存；遗失后需重新创建。
- **仅在服务端使用**。嵌入前端页面或客户端应用的密钥可被提取盗用。
- 密钥可随时撤销，撤销后 5 秒内失效。
- 可为密钥设置有效期；不设即长期有效。
- 修改密钥的权限位**无需轮换密钥**，改完即时生效。

### 2.3 身份模式

调用时需明确"这次操作以谁的身份执行"。身份模式**只有两种**，通过是否携带 `X-Bisheng-On-Behalf-Of` 请求头选择：

| 模式 | 请求头 | 数据可见范围 | 资源归属 |
|---|---|---|---|
| **服务账号**（默认） | 不传 | 服务账号被授权的范围 | 服务账号 |
| **代表平台用户** | `X-Bisheng-On-Behalf-Of` | **该用户在 BiSheng 中的权限范围** | 被代表用户 |

此外还有一个可选的 `X-Bisheng-End-User` 头（§2.3.3），用于按你自己的终端用户分区会话。**它不是第三种身份模式**——传与不传，数据可见范围完全相同。

两个身份头**互斥**，同时传入返回 `26010`。

#### 2.3.1 服务账号模式

不传 `X-Bisheng-On-Behalf-Of`。所有操作以密钥主体身份执行，数据范围即该服务账号被授权的范围。

适用于两类情况：

- **系统集成**——后台任务、数据管道，本来就没有"终端用户"的概念
- **对外应用**——你的使用者与 BiSheng 无账号关系，不应受平台用户权限体系约束。此时请配合 §2.3.3 的 `X-Bisheng-End-User` 头做会话分区

两类情况的接口行为完全一致，差别在于**如何设定服务账号的授权范围**：

> ⚠️ 对外应用请按"哪些内容可以对外部访客开放"从严授权。**这个范围就是该应用的数据出口边界**——服务账号被授予什么，外部访客就可能检索到什么。同样一次配宽，在内部集成上是越权，在对外应用上是公网数据泄漏。

#### 2.3.2 代表平台用户模式

```
X-Bisheng-On-Behalf-Of: 10086
```

取值为平台用户 ID 或用户名，**每次调用指定一个用户**。适用于你的应用使用者就是 BiSheng 平台用户的情况——检索结果、资源列表会与该用户在 BiSheng 中看到的一致；创建的资源归属该用户，他在 BiSheng 中可以直接看到并管理。

**权限基准整体替换为被代表用户**，不多也不少：不会因为走了 API 而少给他有权访问的内容，也不会让他看到无权访问的内容。

> **这是授权委托，不是身份认证。** 它声称的不是"该用户本人正在操作"——任何平台都无法凭一个请求头证明这一点。它声称的是"平台管理员已授权这个集成方，可以按该用户的权限边界执行，并把结果归属给他"。安全性来自密钥的保密性、委托能力的显式授予与审计双归属，从不来自这个头本身。

使用前提（任一不满足将拒绝执行）：

| 前提 | 不满足时 |
|---|---|
| 密钥已被授予 `delegate` 权限位 | `26004` |
| 目标用户须在**可代表范围**内——管理员用「指定用户」或「部门（含子树）」圈定这把密钥允许代表哪些人；该范围为必填项，未配置即无法代表任何人 | `26004` |
| 目标用户已存在于平台、账号可用、且与密钥属于同一租户 | `26005` |
| 目标用户不得是超级管理员或租户管理员 | `26007` |
| 该接口支持代表模式（见各接口的"支持的身份模式"） | `26006` |

> 最后两条是平台的安全底线：**不允许代表管理员身份执行**，避免通过代表机制取得无边界权限。请为集成场景使用普通用户身份。

**关于委托后的权限边界**：委托是权限基准的**替换**，不是收窄。调用方最多获得可代表范围内某个真实用户的真实权限——可能宽于服务账号自身，但永远够不到管理员那两类无条件放行的身份。请据此设定可代表范围。

#### 具备委托能力的密钥必须每次声明被代表用户

密钥一旦被授予委托能力，它的**每一次**调用都必须携带 `X-Bisheng-On-Behalf-Of`，漏传返回 `26016`（HTTP 400）。没有"可代表也可不代表"的混用密钥——一把密钥的身份模式在签发时就已确定。

> **漏传身份头不会降级执行**——不会返回全量数据，不会返回某个"安全的"公开子集，也不会静默改以服务账号身份执行。这是刻意的设计：静默降级会让你以为拿到的是该用户的数据，而实际上给多了是越权、给少了是功能缺失，且从响应上完全无从察觉。报错能让问题在联调阶段就暴露。

如果同一个集成既要以服务账号身份跑后台任务、又要代表用户执行，请让管理员签发**两把**密钥：一把不带委托能力（服务账号模式），一把带委托能力（代表模式）。

#### 2.3.3 外部用户标识（可选）

```
X-Bisheng-End-User: crm-user-88f3a2
```

取值为你自己的用户标识，格式与含义完全由你定义。

> **`X-Bisheng-End-User` 仅用于会话隔离与审计留痕，不参与任何权限判定。** 平台不认识、不校验、不解析该标识。传与不传，数据可见范围完全相同，**均等于密钥主体（服务账号）的权限边界**。

因此，对外应用能访问的数据边界，请通过**给服务账号授予恰当的资源范围**来界定，而不是依赖这个头。

对于工作流、助手这类有会话语义的接口，**建议始终传入该头**。会话本身按接口返回的 `session_id` / `chat_id` 隔离，不传该头不会导致终端用户之间读到彼此的对话；但所有会话会统一归属服务账号，你将无法按终端用户维度做问题追溯。

与 `X-Bisheng-On-Behalf-Of` 同时传入将返回 `26010`——代表平台用户时，会话已归属该用户，无需再做外部分区。

### 2.4 通用响应结构

多数接口返回统一包装：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": { }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | integer | 业务状态码，成功固定为 `200`。 |
| `status_message` | string | 业务状态说明，成功通常为 `SUCCESS`。 |
| `data` | object/array/null | 业务数据，随接口而异；无返回数据的接口为 `null`。 |

**以下接口不使用该包装**，接入时请按各自章节的说明单独处理：

| 接口 | 响应形态 |
|---|---|
| `POST /workflow/invoke`（`stream=true`） | SSE 事件流，见 §4.1.1 |
| `POST /assistant/chat/completions` | OpenAI 原生结构（流式与非流式都不包装），见 §5.1 |
| `POST /chat/liked`、`POST /chat/solved` | `{"status_code": 200, "status_message": "success"}`，**无 `data` 字段** |

### 2.5 错误码

#### 认证与授权

| 业务码 | HTTP | 含义 | 处理建议 |
|---|---|---|---|
| `26001` | 401 | 缺少 API 密钥或格式非法 | 检查 `Authorization` 头格式 |
| `26002` | 401 | 密钥无效、已撤销或已过期 | 更换有效密钥 |
| `26003` | 403 | 密钥缺少本接口所需的权限位 | 在密钥管理中补充权限位；错误信息会指明缺哪一位 |
| `26004` | 403 | 密钥未被授予代表能力，或目标用户不在可代表范围内 | 联系管理员开启 `delegate` 或调整可代表范围 |
| `26005` | 403 | 代表的目标用户不存在、已禁用或跨租户 | 核对用户 ID/用户名 |
| `26006` | 403 | 该接口不支持代表模式 | 改用服务账号模式 |
| `26007` | 403 | 不允许代表超级管理员或租户管理员 | 改用普通用户身份 |
| `26010` | 400 | 身份头冲突（两个身份头同时传入） | 只保留一个身份头 |
| `26016` | 400 | 密钥具备委托能力，但未传 `X-Bisheng-On-Behalf-Of` | 补上身份头；该密钥不允许以服务账号身份调用，需要服务账号模式请另签一把不带委托能力的密钥 |

除上述之外，**资源权限不足**会返回各业务模块自身的错误码（而非 `26003`）——这是刻意区分的，见 §2.2「两层授权」。

#### 通用 HTTP 状态码

| 状态码 | 含义 |
|---|---|
| `200` | 请求成功（业务是否成功仍需看 `status_code`） |
| `201` | 资源创建成功 |
| `400` | 请求参数校验失败，响应体 `detail` 中包含具体字段与原因 |
| `401` | 未认证 |
| `403` | 无权限 |
| `404` | 目标资源不存在 |
| `500` | 服务端异常 |

> **权限评估失败时接口会返回 5xx，绝不返回未过滤或部分过滤的结果集。** 收到 5xx 请重试，不要把它当作"没有匹配数据"处理。

---

## 3. 知识库接口

知识资源是知识库能力的统一载体，包含四种类型：

| `type` | 类型 | 说明 |
|---|---|---|
| `0` | 文档知识库 | 上传文档，自动解析切分并建立检索索引 |
| `1` | QA 知识库 | 以问答对形式组织内容 |
| `2` | 个人知识库 | 归属个人的文档知识库 |
| `3` | 知识空间 | 支持文件夹层级组织的知识库 |

多数接口对四种类型通用，调用方只需传资源 ID，无需区分具体类型。

### 3.1 知识资源层级

#### 3.1.1 获取知识资源列表

**接口地址**　`GET /filelib/`

**接口说明**　按类型、名称和分页查询当前调用身份可见的知识资源。

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `type` | integer | 否 | `0` | 资源类型：`0` 文档知识库，`1` QA 知识库，`2` 个人知识库，`3` 知识空间。 |
| `name` | string | 否 | 无 | 按名称搜索，知识库名称与知识空间名称都匹配此字段。 |
| `sort_by` | string | 否 | `update_time` | 排序字段：`update_time` / `create_time` / `name`。 |
| `page_size` | integer | 否 | `10` | 每页数量。 |
| `cursor` | string | 否 | 无 | 游标分页 token，取上一页响应的 `next_cursor`；首页不传。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.data` | array | 当前页的知识资源列表。 |
| `data.page_size` | integer | 每页数量。 |
| `data.has_more` | boolean | 是否还有下一页。 |
| `data.next_cursor` | string | 下一页游标；无更多数据时为 `null`。 |
| `id` | integer | 知识资源 ID。 |
| `name` | string | 知识资源名称。 |
| `type` | integer | 资源类型。 |
| `description` | string | 资源描述。 |
| `model` | string | Embedding 模型 ID。 |
| `state` | integer | 资源状态。 |
| `auth_type` | string | 访问方式：`public` 公开，`private` 私有，`approval` 需审批。 |
| `is_released` | boolean | 是否发布到知识广场。 |
| `user_id` | integer | 创建人 ID。 |
| `user_name` | string | 创建人名称。 |
| `create_time` | string | 创建时间。 |
| `update_time` | string | 更新时间。 |
| `permission_ids` | array | 当前调用身份对该资源拥有的权限点。 |

#### 3.1.2 创建知识资源

**接口地址**　`POST /filelib/`

**接口说明**　创建一个知识资源，通过 `type` 区分创建哪一类。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

> 使用代表平台用户模式时，创建出的知识资源归属被代表用户，该用户在 BiSheng 中可直接看到并管理。

**入参**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 | 无 | 知识资源名称。 |
| `type` | integer | 否 | `0` | 资源类型。当前支持 `0` / `1` / `3`。 |
| `description` | string | 否 | 无 | 知识资源描述。 |
| `model` | string | 是 | 无 | Embedding 模型 ID，用于后续文档向量化检索。 |
| `auth_type` | string | 否 | `public` | 访问方式：`public` 公开，`private` 私有，`approval` 需审批。 |
| `is_released` | boolean | 否 | `false` | 是否发布到知识广场。主要用于知识空间。 |

**出参**　`data` 为创建成功的知识资源对象，字段同 3.1.1 列表项。

#### 3.1.3 更新知识资源

**接口地址**　`PUT /filelib/`

**接口说明**　更新知识资源的名称与描述。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `knowledge_id` | integer | 是 | 无 | 要更新的知识资源 ID。 |
| `name` | string | 否 | 不传则不修改 | 新的知识资源名称。 |
| `description` | string | 否 | 不传则将描述置空 | 新的知识资源描述。 |

**出参**　`data` 为更新后的知识资源对象，字段同 3.1.1 列表项。

#### 3.1.4 删除知识资源

**接口地址**　`DELETE /filelib/{knowledge_id}`

**接口说明**　删除指定知识资源及其全部内容。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识资源 ID（路径参数）。 |

**出参**　`data` 为 `null`，`status_message` 返回 `knowledge deleted successfully`。

#### 3.1.5 清空知识资源内容

**接口地址**　`DELETE /filelib/clear/{knowledge_id}`

**接口说明**　清空知识资源下的文件内容与检索索引，保留资源本身。资源 ID、名称、描述、配置均不变，仅内容被清空。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识资源 ID（路径参数）。 |

**出参**　`data` 为 `null`，`status_message` 返回 `knowledge clear successfully`。

#### 3.1.6 检索知识资源分段 ★

**接口地址**　`POST /filelib/retrieve`

**接口说明**　跨一个或多个知识资源执行语义检索，返回最相关的文本分段。不做大模型生成，适合自带模型的应用集成。

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

> 这是知识库能力中最常用的接口。若你的应用使用者是平台用户，请使用代表平台用户模式，检索范围会自动收敛到该用户有权访问的知识资源。

**⚠️ 权限判定的粒度是知识资源级，不做文件级过滤**

本接口对 `knowledge_base_ids` 中的每个知识资源做一次访问权限校验：无权访问的资源不参与检索。但**一旦某个资源可访问，其中全部文件的分段都可能被检索到**——本接口不在文件粒度上做二次过滤。

若你需要更细的数据边界，请通过**拆分知识资源**来实现（把不同可见范围的文档放进不同的知识资源，再分别授权），不要依赖本接口做文件级收敛。

**请求示例**

```json
{
  "query": "报销标准是多少",
  "knowledge_base_ids": [1, 2],
  "filters": {
    "knowledge_base_filters": [
      {
        "knowledge_base_id": 1,
        "tags": ["财务制度", "2026"],
        "tag_match_mode": "ANY"
      }
    ]
  },
  "top_k": 10,
  "max_content": 15000
}
```

**入参**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | 无 | 检索问题或关键词，最小长度 1。 |
| `knowledge_base_ids` | integer[] | 是 | 无 | 要检索的知识资源 ID 列表，至少 1 个。 |
| `filters` | object | 否 | `null` | 检索过滤器。 |
| `filters.knowledge_base_filters` | array | 否 | `[]` | 按知识资源分别配置标签过滤，每项对应一个资源。 |
| `filters.knowledge_base_filters[].knowledge_base_id` | integer | 是 | 无 | 必须出现在 `knowledge_base_ids` 中，否则返回 400。 |
| `filters.knowledge_base_filters[].tags` | string[] | 是 | 无 | 标签名称（不是标签 ID）。标签的作用域是单个知识资源。 |
| `filters.knowledge_base_filters[].tag_match_mode` | string | 否 | `ANY` | `ANY` 命中任一标签即纳入。 |
| `top_k` | integer | 否 | `10` | 返回分段数量上限，跨资源合并后截断。取值范围 `[1, 200]`。 |
| `max_content` | integer | 否 | `15000` | 单个知识资源内合并文本的字符上限。取值范围 `>= 1`。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.chunks` | array | 检索命中的分段列表。 |
| `data.total` | integer | 本次返回的分段数量。 |
| `content` | string | 分段文本内容。 |
| `knowledge_id` | integer | 分段所属的知识资源 ID。 |
| `document_id` | integer | 分段所属的文件 ID。 |
| `document_name` | string | 分段所属的文件名称。 |
| `chunk_index` | integer | 分段在文件中的序号。 |
| `document_update_time` | string | 源文件最近更新时间。 |

**检索范围与过滤的关系**

- `knowledge_base_ids` 决定**哪些资源参与检索**。
- `filters.knowledge_base_filters` 决定**参与的资源各自如何筛选**。
- 未在 `knowledge_base_filters` 中出现的资源按整库检索，不施加标签过滤。
- 出现在 `knowledge_base_filters` 中但标签无匹配文件的资源返回 0 条分段，不影响其他资源。
- `max_content` 是单资源内的字符上限，多资源调用时各自独立生效，最终再按 `top_k` 全局截断。
- 无匹配结果时返回 200 + 空数组，**不是错误**。

### 3.2 文档层级

#### 3.2.1 上传文件到知识资源

**接口地址**　`POST /filelib/file/{knowledge_id}`

**接口说明**　向知识资源上传文件，并触发解析、切分与入库。上传后文件进入异步处理队列，可通过文件列表接口的 `status` 字段查询处理进度。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**请求格式**　`multipart/form-data`

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `knowledge_id` | integer | 是 | 无 | 知识资源 ID（路径参数）。 |
| `file` | file | 否 | 无 | 要上传的文件。与 `file_url` 二选一。 |
| `file_url` | string | 否 | 无 | 文件的可下载地址，由服务端拉取。与 `file` 二选一，适合文件已在你自己的对象存储上的场景。 |
| `parent_id` | integer | 否 | 无 | 目标文件夹 ID。仅知识空间使用；不传表示上传到根目录。普通知识库无需传。 |
| `split_mode` | string | 否 | `auto` | 分段模式：`auto` 自动，`custom` 自定义分隔符，`hierarchical` 层级分段。 |
| `separator` | string[] | 否 | 无 | 自定义分隔符列表，`split_mode=custom` 时生效。 |
| `separator_rule` | string[] | 否 | 无 | 分隔符切分位置，与 `separator` 一一对应：`before` 在分隔符前切，`after` 在分隔符后切。 |
| `chunk_size` | integer | 否 | 无 | 目标分段长度（字符数）。 |
| `chunk_overlap` | integer | 否 | 无 | 相邻分段的重叠长度（字符数）。 |
| `hierarchy_level` | integer | 否 | `3` | 层级分段的层数，`split_mode=hierarchical` 时生效。 |
| `append_title` | boolean | 否 | `false` | 是否在每个分段前拼接所属标题。 |
| `max_chunk_size` | integer | 否 | `1000` | 分段长度上限（字符数）。 |
| `retain_images` | integer | 否 | `1` | 是否保留文档中的图片：`1` 保留，`0` 丢弃。 |
| `force_ocr` | integer | 否 | `0` | 是否强制走 OCR：`1` 强制，`0` 自动判断。 |
| `enable_formula` | integer | 否 | `1` | 是否识别公式：`1` 识别，`0` 不识别。 |
| `filter_page_header_footer` | integer | 否 | `0` | 是否过滤页眉页脚：`1` 过滤，`0` 保留。 |
| `excel_rule` | string | 否 | 无 | Excel 专用解析规则，JSON 字符串。 |
| `callback_url` | string | 否 | 无 | 解析完成后的回调地址。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data` | object | 上传后创建的文件记录。 |
| `id` | integer | 文件 ID。 |
| `knowledge_id` | integer | 文件所属知识资源 ID。 |
| `file_name` | string | 文件名称。 |
| `file_type` | integer | 文件类型：`0` 文件夹，`1` 文件。 |
| `file_source` | string | 文件来源，上传接口为 `upload`。 |
| `file_size` | integer | 文件大小，单位字节。 |
| `status` | integer | 处理状态，见附录 9.2。 |
| `remark` | string | 处理备注或失败原因。 |
| `object_name` | string | 文件在对象存储中的地址。 |
| `create_time` | string | 创建时间。 |
| `update_time` | string | 更新时间。 |

#### 3.2.2 上传文件并附带元数据

**接口地址**　`POST /filelib/chunks`

**接口说明**　上传文件的同时指定分段策略与文件元数据。分段参数与 3.2.1 完全相同，两者的差异只有三处：本接口的 `knowledge_id` 走表单而非路径、`file` 与 `metadata` 均为必填、不支持 `file_url`。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**请求格式**　`multipart/form-data`

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `file` | file | 是 | 无 | 要上传的文件。 |
| `knowledge_id` | integer | 是 | 无 | 目标知识资源 ID。 |
| `metadata` | string | 是 | 无 | 文件元数据，JSON 字符串。 |
| 其余分段与解析参数 | — | 否 | — | 同 3.2.1（`split_mode`、`separator`、`chunk_size`、`max_chunk_size`、`retain_images`、`force_ocr` 等）。 |

**出参**　同 3.2.1。

#### 3.2.3 上传文本内容

**接口地址**　`POST /filelib/chunks_string`

**接口说明**　直接提交文本内容入库，无需先落成文件。适合从其他系统同步结构化文本。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 目标知识资源 ID。 |
| `documents` | array | 是 | 文本内容列表，各项按顺序拼接为一个文件入库。 |
| `documents[].page_content` | string | 是 | 文本内容。 |
| `documents[].metadata` | object | 是 | 文本元数据，其中 `source` 字段作为生成的文件名。 |

**出参**　同 3.2.1。

#### 3.2.4 获取文件列表

**接口地址**　`GET /filelib/file/list`

**接口说明**　按知识资源 ID 获取文件列表。

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `knowledge_id` | integer | 是 | 无 | 知识资源 ID。 |
| `parent_id` | integer | 否 | 无 | 目标文件夹 ID。仅知识空间使用；不传表示列出根目录。普通知识库忽略此参数。 |
| `keyword` | string | 否 | 无 | 文件名或标签关键词。 |
| `status` | integer[] | 否 | 无 | 按处理状态过滤，见附录 9.2。 |
| `page_size` | integer | 否 | `10` | 每页数量。 |
| `cursor` | string | 否 | 无 | 游标分页 token，取上一页响应的 `next_cursor`；首页不传。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.data` | array | 当前页文件列表。 |
| `data.page_size` | integer | 每页数量。 |
| `data.has_more` | boolean | 是否还有下一页。 |
| `data.next_cursor` | string | 下一页游标；无更多数据时为 `null`。 |
| `data.writeable` | boolean | 当前身份对该资源是否有写入权限。 |
| `id` | integer | 文件 ID。 |
| `knowledge_id` | integer | 文件所属知识资源 ID。 |
| `file_name` | string | 文件名称。 |
| `file_type` | integer | 文件类型：`0` 文件夹，`1` 文件。 |
| `file_source` | string | 文件来源。 |
| `file_size` | integer | 文件大小，单位字节。 |
| `status` | integer | 处理状态，见附录 9.2。 |
| `remark` | string | 处理备注或失败原因。 |
| `title` | string | 文件摘要或标题。 |
| `tags` | array | 文件标签列表。 |
| `create_time` | string | 创建时间。 |
| `update_time` | string | 更新时间。 |

#### 3.2.5 删除文件

**接口地址**　`DELETE /filelib/file/{file_id}`

**接口说明**　删除指定文件及其检索索引。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file_id` | integer | 是 | 要删除的文件 ID（路径参数）。 |

**出参**　`data` 为 `null`。

#### 3.2.6 批量删除文件

**接口地址**　`POST /filelib/delete_file`

**接口说明**　批量删除文件及其检索索引。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**　请求体直接为文件 ID 数组：

```json
[101, 102, 103]
```

**出参**　`data` 为 `null`。

### 3.3 元数据层级

元数据分两层：**元数据字段**是知识库级别的字段定义（相当于表结构），**文件用户元数据**是具体文件上的字段取值（相当于表数据）。需先定义字段，再为文件赋值。

#### 3.3.1 获取元数据字段

**接口地址**　`GET /knowledge/get_metadata_fields/{knowledge_id}`

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识库 ID（路径参数）。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.knowledge_id` | integer | 知识库 ID。 |
| `data.metadata_fields` | array | 元数据字段列表。 |
| `field_name` | string | 字段名。 |
| `field_type` | string | 字段类型：`string` 文本，`number` 数值，`time` 时间。 |
| `updated_at` | integer | 字段更新时间，Unix 时间戳。 |

#### 3.3.2 添加元数据字段

**接口地址**　`POST /knowledge/add_metadata_fields`

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识库 ID。 |
| `metadata_fields` | array | 是 | 要添加的元数据字段列表。 |
| `metadata_fields[].field_name` | string | 是 | 字段名，只能使用小写字母、数字、下划线，且必须以小写字母开头。 |
| `metadata_fields[].field_type` | string | 是 | 字段类型：`string` / `number` / `time`。 |

**出参**　`data` 为 boolean，表示是否添加成功。

#### 3.3.3 修改元数据字段

**接口地址**　`PUT /knowledge/modify_metadata_fields`

**接口说明**　修改元数据字段名称。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识库 ID。 |
| `metadata_fields` | array | 是 | 要修改的字段列表。 |
| `metadata_fields[].old_field_name` | string | 是 | 原字段名。 |
| `metadata_fields[].new_field_name` | string | 是 | 新字段名，只能使用小写字母、数字、下划线，且必须以小写字母开头。 |

**出参**　`data` 为 boolean。

#### 3.3.4 删除元数据字段

**接口地址**　`DELETE /knowledge/delete_metadata_fields`

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识库 ID。 |
| `field_names` | string[] | 是 | 要删除的字段名列表。 |

**出参**　`data` 为 boolean。

#### 3.3.5 批量查询文件用户元数据

**接口地址**　`POST /knowledge/file/list_user_metadata`

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识库 ID。 |
| `knowledge_file_ids` | integer[] | 是 | 文件 ID 列表。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data` | object | 文件用户元数据，key 为文件 ID。 |
| `field_value` | string/number | 字段值。 |
| `field_type` | string | 字段类型。 |
| `updated_at` | integer | 更新时间，Unix 时间戳。 |

#### 3.3.6 添加文件用户元数据

**接口地址**　`POST /knowledge/file/add_user_metadata`

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `knowledge_id` | integer | 是 | 无 | 知识库 ID。 |
| `add_metadata_list` | array | 是 | 无 | 文件元数据添加列表。 |
| `add_metadata_list[].knowledge_file_id` | integer | 是 | 无 | 文件 ID。 |
| `add_metadata_list[].user_metadata_list` | array | 是 | 无 | 要添加的元数据列表。 |
| `user_metadata_list[].field_name` | string | 是 | 无 | 元数据字段名，须已在 3.3.2 中定义。 |
| `user_metadata_list[].field_value` | string/number | 否 | `null` | 元数据字段值。 |

**出参**　`data` 为 boolean。

#### 3.3.7 修改文件用户元数据

**接口地址**　`PUT /knowledge/file/modify_user_metadata`

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `knowledge_id` | integer | 是 | 无 | 知识库 ID。 |
| `modify_metadata_list` | array | 是 | 无 | 文件元数据修改列表。 |
| `modify_metadata_list[].knowledge_file_id` | integer | 是 | 无 | 文件 ID。 |
| `modify_metadata_list[].user_metadata_list` | array | 是 | 无 | 要修改的元数据列表。 |
| `user_metadata_list[].field_name` | string | 是 | 无 | 元数据字段名。 |
| `user_metadata_list[].field_value` | string/number | 否 | `null` | 新的元数据字段值。 |

**出参**　`data` 为 boolean。

#### 3.3.8 删除文件用户元数据

**接口地址**　`DELETE /knowledge/file/delete_user_metadata`

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 知识库 ID。 |
| `delete_user_metadatas` | array | 是 | 文件元数据删除列表。 |
| `delete_user_metadatas[].knowledge_file_id` | integer | 是 | 文件 ID。 |
| `delete_user_metadatas[].field_names` | string[] | 是 | 要删除的字段名列表。 |

**出参**　`data` 为 boolean。

### 3.4 问答对层级

面向 QA 知识库（`type=1`）的问答对管理。一个问答对包含一组等价问法与一组答案。

#### 3.4.1 新增问答对

**接口地址**　`POST /filelib/add_qa`

**接口说明**　批量向 QA 知识库新增问答对，新增后自动建立检索索引。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | QA 知识库 ID。 |
| `data` | array | 是 | 要新增的问答对列表。 |
| `data[].question` | string | 是 | 问题。 |
| `data[].answer` | string[] | 是 | 答案列表，可给出多条答案。 |
| `data[].extra` | object | 否 | 附加信息，原样存储。 |

**出参**　`data` 为新增成功的问答对对象数组，字段见附录 9.3。

#### 3.4.2 追加相似问法

**接口地址**　`POST /filelib/add_relative_qa`

**接口说明**　为已有问答对追加等价问法，扩大该问答对的召回覆盖面。答案不变。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | QA 知识库 ID。 |
| `data` | object | 是 | 追加参数。 |
| `data.id` | string | 是 | 目标问答对 ID。 |
| `data.relative_questions` | string[] | 是 | 要追加的相似问法列表。 |

**出参**　`data` 为更新后的问答对对象，字段见附录 9.3。问答对不存在时返回 404。

#### 3.4.3 修改问答对

**接口地址**　`POST /filelib/update_qa`

**接口说明**　修改问答对的问题或答案。修改问题会重建该问答对的检索索引。

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | integer | 是 | 问答对 ID。 |
| `question` | string | 否 | 新的问题内容。 |
| `original_question` | string | 否 | 要被替换的原问题。传入时只替换该条问法，其余问法保留；不传时用 `question` 覆盖全部问法。 |
| `answer` | string[] | 否 | 新的答案列表。不传则答案不变。 |

**出参**　`data` 为 `null`。

#### 3.4.4 删除问答对

**接口地址**　`DELETE /filelib/qa/{qa_id}`

**所需权限位**　`knowledge:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `qa_id` | integer | 是 | 问答对 ID（路径参数）。 |
| `question` | string | 否 | 传入时只删除该条问法并保留问答对；不传时删除整个问答对。 |

**出参**　`data` 为 `null`。

#### 3.4.5 获取问答对详情

**接口地址**　`GET /filelib/detail_qa`

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | integer | 是 | 问答对 ID。 |

**出参**　`data` 为问答对对象，字段见附录 9.3。

#### 3.4.6 按时间范围查询问答对

**接口地址**　`POST /filelib/query_qa`

**接口说明**　查询指定时间范围内、通过页面录入或审核沉淀产生的问答对。通过接口创建的问答对不在返回范围内。

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `timeRange` | string[] | 是 | 长度为 2 的数组，`[开始时间, 结束时间]`，格式 `YYYY-MM-DD HH:mm:ss`。 |

**出参**　`data` 为问答对对象数组，字段见附录 9.3。

### 3.5 引用溯源

#### 3.5.1 获取引用详情

**接口地址**　`GET /citation/{citation_id}`

**接口说明**　根据引用 ID 查询该引用指向的源文件信息，用于在你自己的界面上呈现"这段答案出自哪份文档的哪个位置"。引用 ID 出现在助手与工作流回复的引用标记中。

**所需权限位**　`knowledge:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `citation_id` | string | 是 | 引用 ID（路径参数）。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.file_id` | integer | 源文件 ID。 |
| `data.file_name` | string | 源文件名称。 |
| `data.file_type` | string | 源文件类型。 |
| `data.knowledge_name` | string | 源文件所属知识资源名称。 |
| `data.download_url` | string | 源文件下载地址。 |
| `data.preview_url` | string | 源文件预览地址。 |
| `data.bbox` | string | 引用内容在原文中的位置信息，JSON 字符串。 |

以上字段均可能为 `null`。

> **引用不存在、类型不支持、源文件已删除、或当前身份无权访问该文件，一律返回 404。** 这是刻意设计——不区分这几种情况，避免通过响应差异推断出某个引用或文件是否存在。

---

## 4. 工作流接口

### 4.1 调用工作流

**接口地址**　`POST /workflow/invoke`

**接口说明**　触发一条工作流执行。支持流式与同步两种返回方式，并支持工作流中途要求用户输入时的多轮续跑。

**所需权限位**　`workflow:invoke`

**支持的身份模式**　服务账号 / 代表平台用户

> **只有已上线的工作流可以通过本接口调用。** 草稿态工作流会被拒绝执行——请先在平台上完成上线，再接入调用。

**入参**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `workflow_id` | string | 是 | 无 | 工作流 ID（UUID）。 |
| `stream` | boolean | 否 | `true` | `true` 以 SSE 流式返回；`false` 等待执行结束后一次性返回全部事件。 |
| `session_id` | string | 否 | 无 | 会话 ID。首次调用不传，由服务端生成并在响应中返回；续跑时必须原样回传。 |
| `input` | object | 否 | 无 | 用户输入内容。仅在工作流处于等待输入状态时需要。 |
| `message_id` | integer | 否 | 无 | 消息 ID。提交用户输入时必填，取自 `input` 事件返回的 `message_id`。 |
| `override` | object | 否 | 无 | 节点参数覆盖，用于在本次执行中临时调整工作流节点配置。 |

#### 4.1.1 流式返回（`stream=true`）

响应为 `text/event-stream`，每条事件形如：

```
data: {"session_id":"<会话ID>","data":{"event":"stream_msg","status":"start", ...}}
```

**事件类型**

| `event` | 含义 |
|---|---|
| `guide_word` | 开场引导语 |
| `guide_question` | 引导问题 |
| `output_msg` | 完整输出内容 |
| `stream_msg` | 流式输出片段，通过 `status` 区分 `start` / `end` |
| `output_with_input_msg` | 输出内容并要求用户输入 |
| `output_with_choose_msg` | 输出内容并要求用户选择 |
| `input` | 工作流等待用户输入 |
| `close` | 本次执行结束 |
| `error` | 执行出错 |

**事件字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | string | 会话 ID，续跑时需回传。 |
| `data.event` | string | 事件类型。 |
| `data.status` | string | 事件状态，流式输出用 `start` / `end` 区分。 |
| `data.message_id` | string | 消息 ID，提交用户输入时需要。 |
| `data.node_id` | string | 产生该事件的节点 ID。 |
| `data.node_name` | string | 节点名称。 |
| `data.node_execution_id` | string | 节点本次执行的唯一 ID。 |
| `data.output_schema.message` | any | 输出的消息内容。 |
| `data.output_schema.reasoning_content` | string | 推理过程内容。 |
| `data.output_schema.files` | array | 输出的文件列表。 |
| `data.input_schema.input_type` | string | 输入形态：`dialog` 对话框输入，`form` 表单输入。 |
| `data.input_schema.value` | array | 需要用户填写的输入项定义。 |

**输入项定义**（`input_schema.value[]`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | string | 输入项标识，提交时作为 `input` 的 key。 |
| `type` | string | 输入类型：`dialog` 文本、`select` 选择、`file` 文件。 |
| `label` | string | 输入项显示名称。 |
| `value` | any | 默认值。 |
| `required` | boolean | 是否必填。 |
| `multiple` | boolean | 是否多选。 |
| `options` | array | 选项列表，`type=select` 时提供。 |
| `file_type` | string | 允许上传的文件类型，`type=file` 时提供。 |

#### 4.1.2 同步返回（`stream=false`）

服务端等待执行结束后一次性返回：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "session_id": "a1b2c3d4_async_task_id",
    "events": [ ]
  }
}
```

`events` 为本次执行产生的全部事件数组，事件结构同 4.1.1，但不含 `stream_msg` 类型的中间流式片段。

#### 4.1.3 多轮输入交互

工作流中途需要用户输入时，流程如下：

1. 首次调用不传 `session_id`，从响应中取得 `session_id`。
2. 收到 `input`（或 `output_with_input_msg` / `output_with_choose_msg`）事件时，记录事件中的 `message_id` 与 `input_schema`。
3. 携带同一个 `session_id`、上一步的 `message_id`，以及按 `input_schema` 组装的 `input` 对象再次调用本接口，工作流从中断处继续执行。
4. 重复步骤 2–3 直至收到 `close` 事件。

`input` 对象的 key 取自 `input_schema.value[].key`：

```json
{
  "workflow_id": "……",
  "session_id": "a1b2c3d4_async_task_id",
  "message_id": 12345,
  "input": {
    "user_choice": "同意",
    "remark": "已核对无误"
  }
}
```

### 4.2 停止工作流

**接口地址**　`POST /workflow/stop`

**接口说明**　中止指定会话正在执行的工作流。

**所需权限位**　`workflow:invoke`

**支持的身份模式**　服务账号 / 代表平台用户

> **只能停止属于当前调用身份的会话。** 试图停止其他身份创建的会话将返回 403。

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `workflow_id` | string | 是 | 工作流 ID（UUID）。 |
| `session_id` | string | 是 | 要停止的会话 ID。 |

**出参**　`data` 为 `null`。

### 4.3 获取工作流信息

**接口地址**　`GET /flows/{flow_id}`

**接口说明**　查询一条工作流的配置信息，可用于在调用前确认工作流的输入项定义。

**所需权限位**　`workflow:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `flow_id` | string | 是 | 工作流 ID（路径参数，UUID）。 |

**出参**　`data` 为工作流对象，含 ID、名称、描述、状态、节点配置等信息。

工作流不存在、或该 ID 指向的不是工作流时返回 404；当前身份无权查看该工作流时返回无权限错误。

---

## 5. 助手接口

### 5.1 助手对话

**接口地址**　`POST /assistant/chat/completions`

**接口说明**　以 OpenAI Chat Completions 兼容格式调用智能助手。已有 OpenAI SDK 的应用可直接替换 base URL 与 model 接入。

**所需权限位**　`assistant:invoke`

**支持的身份模式**　服务账号 / 代表平台用户

> **本接口的响应不使用 §2.4 的统一包装**，流式与非流式均返回 OpenAI 原生结构，以保证 SDK 兼容性。

**入参**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `model` | string | 是 | 无 | **填助手 ID**。 |
| `messages` | array | 是 | 无 | 对话消息列表，支持 `user` 与 `assistant` 两种角色。系统提示词取助手自身配置，无需传入。 |
| `messages[].role` | string | 是 | 无 | `user` 或 `assistant`。 |
| `messages[].content` | string | 是 | 无 | 消息内容。 |
| `stream` | boolean | 否 | `false` | 是否流式返回。 |
| `temperature` | float | 否 | `0.0` | 模型温度。传 `0` 或不传表示沿用助手自身配置。 |
| `n` | integer | 否 | `1` | 返回结果数量，当前仅支持 `1`。 |
| `tools` | array | 否 | `[]` | **本接口忽略此字段**。助手可用的工具取助手自身配置，不能在调用时指定。 |

**出参（非流式）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 本次回复 ID。 |
| `object` | string | 固定为 `chat.completion`。 |
| `created` | integer | 创建时间，Unix 时间戳。 |
| `model` | string | 助手 ID。 |
| `choices` | array | 回复列表。 |
| `choices[].index` | integer | 选项序号。 |
| `choices[].message` | object | 回复消息，含 `role` 与 `content`。 |
| `choices[].finish_reason` | string | 结束原因，固定为 `stop`。 |

**出参（流式，`stream=true`）**

响应为 `text/event-stream`，每条形如 `data: {...}`，`object` 为 `chat.completion.chunk`，增量内容位于 `choices[].delta.content`；思考过程位于 `choices[].delta.reasoning_content`。流以 `data: [DONE]` 结束。

> 若助手所选模型不支持流式输出，接口仍会以 SSE 形式返回，但内容会在一条 chunk 中一次性给出。

### 5.2 获取助手详情

**接口地址**　`GET /assistant/info/{assistant_id}`

**所需权限位**　`assistant:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `assistant_id` | string | 是 | 助手 ID（路径参数，UUID）。 |

**出参**　`data` 为助手对象，含 ID、名称、描述、开场白、引导问题，以及该助手关联的工具列表、工作流列表与知识库列表。

### 5.3 获取助手列表

**接口地址**　`GET /assistant/list`

**接口说明**　查询当前调用身份可见的助手列表。

**所需权限位**　`assistant:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | 否 | 无 | 按名称模糊搜索，同时匹配描述。 |
| `tag_id` | integer | 否 | 无 | 按标签过滤。 |
| `status` | integer | 否 | 无 | 按上线状态过滤。 |
| `page` | integer | 否 | `1` | 页码，从 1 开始。 |
| `limit` | integer | 否 | `10` | 每页数量。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.data` | array | 当前页助手列表。 |
| `data.total` | integer | 符合条件的助手总数。 |
| `id` | string | 助手 ID。 |
| `name` | string | 助手名称。 |
| `desc` | string | 助手描述。 |
| `logo` | string | 助手图标地址。 |
| `status` | integer | 上线状态。 |
| `user_id` | integer | 创建人 ID。 |
| `user_name` | string | 创建人名称。 |
| `tags` | array | 标签列表。 |
| `create_time` | string | 创建时间。 |
| `update_time` | string | 更新时间。 |

> 返回范围由**当前调用身份**决定：服务账号模式下是该服务账号被授权的助手，代表平台用户模式下是被代表用户可见的助手。

---

## 6. 会话记录接口

本章接口用于读写**会话与消息记录**——包括通过工作流、助手等任何路径产生的会话。

它们与"发起一次对话"是两类不同的动作，因此使用独立的 `session:*` 权限位：读取历史用 `session:read`，写入用户反馈用 `session:write`，回填消息用 `session:sync`。

### 6.1 获取会话历史

**接口地址**　`GET /chat/history`

**接口说明**　按会话 ID 分页获取消息记录，用于在你自己的界面上还原对话。

**所需权限位**　`session:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `chat_id` | string | 是 | 无 | 会话 ID。 |
| `flow_id` | string | 是 | 无 | 该会话所属的工作流或助手 ID。与 `chat_id` 不匹配时返回空数组。 |
| `id` | string | 否 | 无 | 游标：传入某条消息 ID，返回比它更早的消息。首页不传。 |
| `page_size` | integer | 否 | `20` | 每页数量。 |

**出参**　`data` 为消息数组，按时间排列。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 消息 ID。 |
| `chat_id` | string | 所属会话 ID。 |
| `flow_id` | string | 所属工作流或助手 ID。 |
| `is_bot` | boolean | 是否为机器回复。 |
| `message` | string | 消息内容。 |
| `type` | string | 消息类型。 |
| `category` | string | 消息分类。 |
| `sender` | string | 发送方名称。 |
| `receiver` | object | 接收方信息。 |
| `files` | string | 消息附带的文件列表，JSON 字符串。 |
| `intermediate_steps` | string | 中间执行过程。 |
| `extra` | string | 附加信息，JSON 字符串。 |
| `liked` | integer | 点赞状态：`0` 未评价，`1` 赞，`2` 踩。 |
| `solved` | integer | 会话解决状态：`0` 未评价，`1` 已解决，`2` 未解决。 |
| `copied` | integer | 是否被复制过。 |
| `remark` | string | 用户评论内容。 |
| `source` | integer | 是否支持溯源。 |
| `mark_status` | integer | 标注状态。 |
| `mark_user` | integer | 标注人 ID。 |
| `mark_user_name` | string | 标注人名称。 |
| `sensitive_status` | integer | 内容安全审查状态。 |
| `user_id` | integer | 消息归属用户 ID。 |
| `user_name` | string | 消息归属用户名称。 |
| `flow_name` | string | 工作流或助手名称。 |
| `name` | string | 会话名称。 |
| `create_time` | string | 创建时间。 |
| `update_time` | string | 更新时间。 |

> `chat_id` 与 `flow_id` 任一为空、或两者不匹配时，返回 200 + 空数组，不报错。

### 6.2 生成会话标题

**接口地址**　`POST /chat/gen_title`

**接口说明**　获取会话的展示标题。

**所需权限位**　`session:read`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `conversationId` | string | 是 | 会话 ID。 |

**出参**

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.title` | string | 会话标题。 |

> ⚠️ **本接口存在约 5 秒的服务端等待**（用于让标题生成完成），请把客户端超时设为 5 秒以上。
> 会话不存在时返回 `"New Chat"` 而非报错。

### 6.3 消息点赞与点踩

**接口地址**　`POST /chat/liked`

**接口说明**　为一条机器回复记录用户的赞或踩。

**所需权限位**　`session:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `message_id` | integer | 是 | 消息 ID。 |
| `liked` | integer | 是 | `0` 未评价，`1` 赞，`2` 踩。 |

**出参**　**不使用统一包装**，返回：

```json
{"status_code": 200, "status_message": "success"}
```

### 6.4 标记会话解决状态

**接口地址**　`POST /chat/solved`

**接口说明**　标记整个会话是否已解决用户的问题，用于会话质量统计。

**所需权限位**　`session:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `chat_id` | string | 是 | 会话 ID。 |
| `solved` | integer | 是 | `0` 未评价，`1` 已解决，`2` 未解决。 |

**出参**　**不使用统一包装**，返回：

```json
{"status_code": 200, "status_message": "success"}
```

### 6.5 提交消息评论

**接口地址**　`POST /chat/comment`

**接口说明**　为一条消息提交文字反馈，通常与点踩配合使用，用于收集"为什么不满意"。

**所需权限位**　`session:write`

**支持的身份模式**　服务账号 / 代表平台用户

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `message_id` | integer | 是 | 消息 ID。 |
| `comment` | string | 否 | 评论内容。**超过 4096 字符的部分会被截断。** |

**出参**　`data` 为 `null`。

> 本接口只写入评论。请求体中的 `liked` 字段会被忽略——点赞与点踩请使用 §6.3。

### 6.6 回填会话消息

**接口地址**　`POST /chat/sync/messages`

**接口说明**　把你自己系统中产生的对话消息写入指定会话，使其出现在 BiSheng 的会话记录中。适用于人工客服接管、外部渠道消息归档等场景。

**所需权限位**　`session:sync`

**支持的身份模式**　服务账号 / 代表平台用户

> ⚠️ **这是本文档中风险最高的写入接口**，因此单独占用 `session:sync` 权限位、不并入 `session:write`：它可以向会话写入任意内容的消息，等同于改写对话记录；而点赞、评论这类反馈只改元数据。**请只给确有归档需求的集成授予此权限位。**

**入参**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `flow_id` | string | 是 | 会话所属的工作流或助手 ID（UUID）。 |
| `chat_id` | string | 是 | 目标会话 ID。 |
| `message_list` | array | 是 | 要写入的消息列表。 |
| `message_list[].is_send` | boolean | 是 | 消息方向标识。 |
| `message_list[].message` | string | 是 | 消息内容。 |
| `message_list[].create_time` | string | 是 | 消息产生时间，格式 `YYYY-MM-DD HH:mm:ss`。 |
| `message_list[].extra` | object | 是 | 附加信息，原样存储。 |

**出参**　`data` 为 `null`。

---

## 7. 调用示例

### 7.1 服务账号模式：检索知识库

系统集成场景，以服务账号自身权限检索。

```bash
curl -X POST 'https://<你的部署域名>/api/v2/filelib/retrieve' \
  -H 'Authorization: Bearer bs-sak-xxxxxxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "差旅费报销标准",
    "knowledge_base_ids": [1, 2],
    "top_k": 5
  }'
```

### 7.2 代表平台用户模式：按员工权限检索

企业内部应用场景，检索范围收敛到该员工有权访问的知识资源。

```bash
curl -X POST 'https://<你的部署域名>/api/v2/filelib/retrieve' \
  -H 'Authorization: Bearer bs-sak-xxxxxxxxxxxx' \
  -H 'X-Bisheng-On-Behalf-Of: 10086' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "差旅费报销标准",
    "knowledge_base_ids": [1, 2],
    "top_k": 5
  }'
```

### 7.3 服务账号模式 + 外部用户标识：调用工作流

对外应用场景。身份仍是服务账号（权限范围不因这个头而改变），额外传入 `X-Bisheng-End-User` 以隔离各终端用户的会话。

```bash
curl -X POST 'https://<你的部署域名>/api/v2/workflow/invoke' \
  -H 'Authorization: Bearer bs-sak-xxxxxxxxxxxx' \
  -H 'X-Bisheng-End-User: crm-user-88f3a2' \
  -H 'Content-Type: application/json' \
  -d '{
    "workflow_id": "3fa85f6457174562b3fc2c963f66afa6",
    "stream": false,
    "input": {"question": "帮我查一下订单状态"}
  }'
```

### 7.4 Python 集成示例

```python
import httpx

BASE_URL = "https://<你的部署域名>/api/v2"
API_KEY = "bs-sak-xxxxxxxxxxxx"


def build_headers(on_behalf_of: int | None = None,
                  end_user: str | None = None) -> dict:
    """构造请求头。on_behalf_of 与 end_user 互斥，最多传一个。"""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if on_behalf_of is not None:
        headers["X-Bisheng-On-Behalf-Of"] = str(on_behalf_of)
    elif end_user is not None:
        headers["X-Bisheng-End-User"] = end_user
    return headers


def retrieve(query: str, kb_ids: list[int], user_id: int | None = None) -> list[dict]:
    """检索知识库。传入 user_id 时按该平台用户的权限过滤。"""
    resp = httpx.post(
        f"{BASE_URL}/filelib/retrieve",
        headers=build_headers(on_behalf_of=user_id),
        json={"query": query, "knowledge_base_ids": kb_ids, "top_k": 5},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]["chunks"]


def invoke_workflow(workflow_id: str, user_input: dict, end_user: str) -> dict:
    """同步调用工作流，按外部用户标识隔离会话。"""
    resp = httpx.post(
        f"{BASE_URL}/workflow/invoke",
        headers=build_headers(end_user=end_user),
        json={"workflow_id": workflow_id, "stream": False, "input": user_input},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_history(chat_id: str, flow_id: str, page_size: int = 20) -> list[dict]:
    """读取会话历史。需要 session:read 权限位。"""
    resp = httpx.get(
        f"{BASE_URL}/chat/history",
        headers=build_headers(),
        params={"chat_id": chat_id, "flow_id": flow_id, "page_size": page_size},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]
```

### 7.5 流式调用工作流

```python
import json
import httpx

with httpx.stream(
    "POST",
    f"{BASE_URL}/workflow/invoke",
    headers=build_headers(end_user="crm-user-88f3a2"),
    json={"workflow_id": workflow_id, "stream": True, "input": {"question": "..."}},
    timeout=120,
) as resp:
    session_id = None
    for line in resp.iter_lines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        session_id = event["session_id"]
        data = event["data"]
        if data["event"] == "stream_msg":
            print(data["output_schema"]["message"], end="", flush=True)
        elif data["event"] == "input":
            # 工作流等待输入：记录 message_id 与 input_schema，续跑时回传
            break
        elif data["event"] == "close":
            break
```

### 7.6 错误处理

业务错误以 HTTP 状态码 + 响应体中的 `status_code` 双重表达，两者都要检查：

```python
def call_api(path: str, **kwargs) -> dict:
    resp = httpx.post(f"{BASE_URL}{path}", **kwargs)

    if resp.status_code == 401:
        raise RuntimeError("密钥无效或已撤销，请更换密钥")
    if resp.status_code == 403:
        body = resp.json()
        code = body.get("status_code")
        if code == 26003:
            raise RuntimeError(f"密钥缺少所需权限位：{body.get('status_message')}")
        if code in (26004, 26005, 26006, 26007):
            raise RuntimeError(f"委托被拒绝：{body.get('status_message')}")
        raise RuntimeError(f"资源权限不足：{body.get('status_message')}")
    if resp.status_code >= 500:
        # 权限评估失败等情况会返回 5xx，且绝不返回部分结果，可安全重试
        raise RuntimeError("服务端异常，请重试")

    resp.raise_for_status()
    return resp.json()["data"]
```

---

## 8. 升级说明

### 8.1 这是一次破坏性变更

本版本发布即启用鉴权，**不提供兼容开关**：升级后所有 `/api/v2` 调用必须携带密钥，无密钥一律返回 401。

之所以不设过渡开关：本次改造关闭的是一条无需任何凭据即可调用、且可指定任意用户身份执行的通道。任何"默认关闭"的兼容开关都意味着升级后通道依然敞着，只有主动去翻开关的客户才真正受到保护。

**请在升级前完成调用方改造。**

### 8.2 升级前必须完成的三步

| 步骤 | 动作 |
|---|---|
| 1 | 在平台创建服务账号，按最小必要授予其所需的知识资源、工作流、助手 |
| 2 | 为该服务账号签发密钥，按需勾选权限位；若集成需要代表平台用户执行，另配可代表范围 |
| 3 | 改造调用方代码：加 `Authorization: Bearer` 请求头；原先在请求参数里传 `user_id` 的调用改为 `X-Bisheng-On-Behalf-Of` 请求头 |

### 8.3 变更清单

| 变更 | 影响 | 应对 |
|---|---|---|
| **全部端点要求密钥** | 无密钥调用返回 401 | 所有请求补 `Authorization` 头 |
| **请求参数中的裸 `user_id` 移除** | 原先在请求体或查询参数里传 `user_id` 指定执行身份的调用会返回参数错误 | 改用 `X-Bisheng-On-Behalf-Of` 请求头，并确保密钥已被授予 `delegate` 权限位与可代表范围 |
| **工作流上线状态校验** | 原先可调用草稿态工作流，现在会被拒绝 | 先在平台上线目标工作流 |
| **停止工作流校验会话归属** | 原先可停止任意会话，现在只能停自己的 | 无需改造，除非你的集成依赖了这个行为 |
| **原「默认操作员」不再作为兜底身份** | 原先所有调用共用一个数据库配置的固定用户，其权限即全部调用的权限边界 | 该用户会被转为服务账号并降权，名下已有资源的归属与可见性不变 |

> 若你此前按旧文档的建议把默认操作员配置成了超级管理员，**升级后该身份会被降权**。请按 §8.2 重新规划服务账号的最小必要授权，不要试图恢复超管配置。

---

## 9. 附录

### 9.1 限制说明

| 项 | 限制 |
|---|---|
| 检索单次返回分段数（`top_k`） | 1 – 200，默认 10 |
| 检索单资源内容长度（`max_content`） | ≥ 1，默认 15000 字符 |
| 检索资源数量（`knowledge_base_ids`） | 至少 1 个 |
| 分段长度上限（`max_chunk_size`） | 默认 1000 字符 |
| 助手返回结果数（`n`） | 仅支持 1 |
| 会话历史每页数量（`page_size`） | 默认 20 |
| 消息评论长度（`comment`） | 4096 字符，超出截断 |
| 生成会话标题的服务端等待 | 约 5 秒，客户端超时须大于此值 |

### 9.2 文件处理状态

| `status` | 含义 |
|---|---|
| `1` | 处理中 |
| `2` | 处理成功 |
| `3` | 处理失败 |
| `4` | 重建中 |
| `5` | 排队中 |
| `6` | 处理超时 |
| `7` | 内容安全违规 |

### 9.3 问答对对象字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 问答对 ID。 |
| `knowledge_id` | integer | 所属 QA 知识库 ID。 |
| `questions` | string[] | 问法列表，包含原始问题与追加的相似问法。 |
| `answers` | string[] | 答案列表。 |
| `user_id` | integer | 创建人 ID。 |
| `source` | integer | 来源：`1` 页面录入，`2` 审核沉淀，`3` 接口创建，`4` 批量导入。 |
| `status` | integer | 状态：`1` 生效，`0` 已关闭，`2` 处理中，`3` 入库失败。 |
| `extra_meta` | string | 附加信息，创建时原样存储。 |
| `remark` | string | 备注。 |
| `create_time` | string | 创建时间。 |
| `update_time` | string | 更新时间。 |

### 9.4 知识资源类型

| `type` | 类型 |
|---|---|
| `0` | 文档知识库 |
| `1` | QA 知识库 |
| `2` | 个人知识库 |
| `3` | 知识空间 |

### 9.5 接口索引

「模式」列：**S** 服务账号模式，**D** 代表平台用户模式。

#### 知识库

| 接口 | 方法与路径 | 权限位 | 模式 |
|---|---|---|---|
| 获取知识资源列表 | `GET /filelib/` | `knowledge:read` | S / D |
| 创建知识资源 | `POST /filelib/` | `knowledge:write` | S / D |
| 更新知识资源 | `PUT /filelib/` | `knowledge:write` | S / D |
| 删除知识资源 | `DELETE /filelib/{knowledge_id}` | `knowledge:write` | S / D |
| 清空知识资源内容 | `DELETE /filelib/clear/{knowledge_id}` | `knowledge:write` | S / D |
| 检索知识资源分段 | `POST /filelib/retrieve` | `knowledge:read` | S / D |
| 上传文件到知识资源 | `POST /filelib/file/{knowledge_id}` | `knowledge:write` | S / D |
| 上传文件并附带元数据 | `POST /filelib/chunks` | `knowledge:write` | S / D |
| 上传文本内容 | `POST /filelib/chunks_string` | `knowledge:write` | S / D |
| 获取文件列表 | `GET /filelib/file/list` | `knowledge:read` | S / D |
| 删除文件 | `DELETE /filelib/file/{file_id}` | `knowledge:write` | S / D |
| 批量删除文件 | `POST /filelib/delete_file` | `knowledge:write` | S / D |
| 获取元数据字段 | `GET /knowledge/get_metadata_fields/{knowledge_id}` | `knowledge:read` | S / D |
| 添加元数据字段 | `POST /knowledge/add_metadata_fields` | `knowledge:write` | S / D |
| 修改元数据字段 | `PUT /knowledge/modify_metadata_fields` | `knowledge:write` | S / D |
| 删除元数据字段 | `DELETE /knowledge/delete_metadata_fields` | `knowledge:write` | S / D |
| 批量查询文件用户元数据 | `POST /knowledge/file/list_user_metadata` | `knowledge:read` | S / D |
| 添加文件用户元数据 | `POST /knowledge/file/add_user_metadata` | `knowledge:write` | S / D |
| 修改文件用户元数据 | `PUT /knowledge/file/modify_user_metadata` | `knowledge:write` | S / D |
| 删除文件用户元数据 | `DELETE /knowledge/file/delete_user_metadata` | `knowledge:write` | S / D |
| 新增问答对 | `POST /filelib/add_qa` | `knowledge:write` | S / D |
| 追加相似问法 | `POST /filelib/add_relative_qa` | `knowledge:write` | S / D |
| 修改问答对 | `POST /filelib/update_qa` | `knowledge:write` | S / D |
| 删除问答对 | `DELETE /filelib/qa/{qa_id}` | `knowledge:write` | S / D |
| 获取问答对详情 | `GET /filelib/detail_qa` | `knowledge:read` | S / D |
| 按时间范围查询问答对 | `POST /filelib/query_qa` | `knowledge:read` | S / D |
| 获取引用详情 | `GET /citation/{citation_id}` | `knowledge:read` | S / D |

#### 工作流

| 接口 | 方法与路径 | 权限位 | 模式 |
|---|---|---|---|
| 调用工作流 | `POST /workflow/invoke` | `workflow:invoke` | S / D |
| 停止工作流 | `POST /workflow/stop` | `workflow:invoke` | S / D |
| 获取工作流信息 | `GET /flows/{flow_id}` | `workflow:read` | S / D |

#### 助手

| 接口 | 方法与路径 | 权限位 | 模式 |
|---|---|---|---|
| 助手对话 | `POST /assistant/chat/completions` | `assistant:invoke` | S / D |
| 获取助手详情 | `GET /assistant/info/{assistant_id}` | `assistant:read` | S / D |
| 获取助手列表 | `GET /assistant/list` | `assistant:read` | S / D |

#### 会话记录

| 接口 | 方法与路径 | 权限位 | 模式 |
|---|---|---|---|
| 获取会话历史 | `GET /chat/history` | `session:read` | S / D |
| 生成会话标题 | `POST /chat/gen_title` | `session:read` | S / D |
| 消息点赞与点踩 | `POST /chat/liked` | `session:write` | S / D |
| 标记会话解决状态 | `POST /chat/solved` | `session:write` | S / D |
| 提交消息评论 | `POST /chat/comment` | `session:write` | S / D |
| 回填会话消息 | `POST /chat/sync/messages` | `session:sync` | S / D |

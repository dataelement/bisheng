# F053 实测问题与修复方案补充

日期：2026-09-08。状态：**服务账号 F048 技术标记修复已在本地发版分支实施，待发布到目标环境；其余问题仍待修复**。

依据：本目录 design.md、本地代码、116 实例 HTTP/数据库/OpenFGA 实测。
测试入口为 `http://192.168.106.116:3001`；该入口经 Nginx 转发至 `192.168.106.115:8098` 网关；116 后端直连端口为 7861。
已核对后端的 dependencies.py、identity_service.py、credential_validator.py、main.py、filelib.py 五个关键文件，与本地文件哈希一致。该核对不代表网关或整个部署代码均已核对。

## 1. 结论与架构裁定

凭据识别和五道委托准入的已测分支可以拒绝非法请求，但**不能据此验收整个开放 API 权限体系**。资源授权、个别业务端点、会话跨访问面隔离仍有问题。

本期设计已明确采用两张表：自然人保留在 `user`，服务账号存放于 `service_account`。统一授权主体是 `(subject_type, subject_id, tenant_id)`，而不是要求全部主体共用 `user` 表。

| 调用方式 | 权限主体 | 业务创建人/归属人 |
|---|---|---|
| 服务账号自身调用 | `service_account:{id}` | `resource_owner_user_id` |
| 服务账号代表用户 | `user:{target_id}` | 被代表用户 |
| 自然人 PAT | `user:{holder_id}` | PAT 持有人 |

建议维持上述架构。当前服务账号失败的直接原因是 F048 权限图对新主体类型的适配不完整。把服务账号伪装成资源归属人，会破坏“独立授权、不继承归属人权限”的要求；把表合并也不能自动修复权限图的类型不匹配。

## 2. P1：服务账号有资源授权，但业务动作不生效

### 2.1 已复现的现象

- 创建账号、签发 SAK、whoami 均成功。
- 授权台账中已存在服务账号的 viewer/editor/manager 授权。
- 服务账号拥有 `knowledge:write`，且被授予空间 editor 后，上传仍返回业务码 `18040`。
- 同一测试文档，用户 PAT/委托用户能检索到正文，服务账号检索为零条。
- 创建资源后的回授也受影响：曾创建成功并获得 manager 回授，但仍不能上传。

直接 OpenFGA Check 取证（测试期间服务账号 4、用户 855、空间 4254；该旧批次已清理）：

| Relation | 已授权服务账号 | 资源所有者用户 |
|---|---:|---:|
| visible | true | true |
| permission_enabled | false | true |
| custom_mode | false | true |
| can_upload_file | false | true |
| can_download | false | true |

### 2.2 原因

`bisheng/core/openfga/authorization_model_f048.py` 已将 `service_account` 加入 `_subject_types()`，允许其成为普通授权对象。但是以下控制标记仍只允许 `user:*`：

- `permission_catalog_release.active`；
- `permission_model_release.enabled_marker`、动作 marker、授权级别 marker；
- 资源的 `permission_enabled`、`custom_mode`、`inherit_mode`。

OpenFGA 的 `user:*` 仅匹配 user 类型，不能覆盖 service_account 类型。

例如上传权限需要同时满足资源启用状态、授权对应的动作权限以及适用的自定义/继承模式。授权对象这一支虽然支持服务账号，其他相交的分支仍只支持 user，最终结果就是 false。顶层 visible 存在直接授权分支，因此会出现“可见，但不能操作”的现象。

### 2.3 推荐修复：模型、投影、存量数据同步适配

1. **区分技术状态标记与业务授权关系。** 为上述主体无关的技术状态标记，统一支持 `user:*` 和 `service_account:*`。这只是让两类主体共同接受启停、版本和模式控制，不代替显式资源授权。
2. **保留自然人的特权边界。** `system.super_admin`、租户管理员、受保护 owner 授权、部门成员等继续保持自然人语义。不能把所有 `user:*` 或所有 user 类型关系全局替换，也不能顺带扩大公开、共享资源对服务账号的可访问范围。
3. **统一生成投影 tuple。** 引入集中定义的技术标记主体集合，模型声明与 tuple 生成使用同一份定义。目录发布、模型启停、动作变更、资源创建/删除/禁用、模式切换、继承链、回滚与对账都同步处理两类 marker。
4. **补齐现有数据。** 仅发布新 OpenFGA 模型不会自动产生 `service_account:*` tuple。需要按现有目录、模型和资源状态生成增量修复计划：先 dry-run，列出精确增删，再执行并校验。不能向所有资源无条件写入 enabled/custom 标记。
5. **保留一致性保障。** 目录版本切换时，两类 active 指针在同一提交批次更新；原有 STAGE 阶段撤销启用、COMMIT 恢复的流程必须同时覆盖两类主体。失败恢复和重试不能只更新 user。
6. **通过真实 OpenFGA 集成测试后部署。** 更新 API/worker 的模型兼容性检查，再按既有发布流程切换模型与投影，验证存量资源、新资源及存量 SAK。

代码落点：

- 模型：`core/openfga/authorization_model_f048.py`。
- 初始目录 tuple：`permission/application/catalog_bootstrap.py`。
- 目录发布与模型动作投影：`permission/application/catalog_api.py`、`permission/domain/services/catalog_service.py`。
- 资源启停与模式切换：`permission/domain/services/resource_lifecycle_policy.py`、`mode_service.py`。
- 资源创建相关标记：`permission/domain/services/owner_service.py`，须区分模式标记与公共可读标记。
- 存量迁移和对账：`permission/migration/f048_coordinator.py` 及既有投影重建路径。

以上代码落点均相对于 `src/backend/bisheng/`。

实施结果：模型版本已提升为 `f048-v4`，技术状态标记统一覆盖 `user:*` 与 `service_account:*`；目录发布、资源生命周期、权限模式切换、正式迁移和存量对账均同步生成两类 tuple。既有 `reconcile_f048_visible_projection.py` 已扩展为 dry-run 默认的存量升级工具，可发布不可变新模型、补齐当前 SQL 资源状态对应的服务账号 marker、校验后切换 Catalog。自然人的超管、租管、受保护 owner、公开与系统共享边界保持不变。

本地定向验证结果：权限模型、目录、投影、迁移与对账 142 passed，真实 OpenFGA 环境测试 6 项因本机没有专用实例而按门禁跳过；开放 API 与知识库回归 103 passed。目标 116 环境尚未执行模型升级和上线后冒烟，因此本节问题在目标环境的状态仍为“待发版验证”。

### 2.4 验收条件

- 同一资源：无授权 SA 拒绝；viewer 能读但不能上传；editor 能上传但不能越过其动作集合；撤销后立即拒绝。
- SA 的资源归属人有权，SA 无权时仍拒绝。
- SA 有权、被代表用户无权时，模式 D 仍拒绝。
- 新创建资源的回授有效，且可撤销。
- 文件/文件夹继承、自定义权限、父级撤权均生效，不能只测空间顶层 visible。
- 资源禁用、模型禁用、目录切换与投影失败时，两类主体均按策略拒绝。
- 不为 SA 增加超管、租管或受保护 owner 身份；用户既有授权不退化。

## 3. P1：QA 端点缺少逐资源鉴权，可越权读写

### 3.1 已复现

- 测试用户无法通过知识库列表看到另一用户的测试 QA 库，但通过 `GET /api/v2/filelib/detail_qa?id=47295` 读到了测试答案。
- 无该库资源授权的服务账号，通过 `POST /api/v2/filelib/update_qa` 修改了该测试答案；HTTP 和业务码均为 200，随后 GET 确认修改已持久化。原值已恢复。
- 全部操作仅针对测试创建的数据，没有修改原有业务问答。

### 3.2 原因与修复

`open_endpoints/api/endpoints/filelib.py` 中相关端点在解析操作主体后直接调用 QA DAO。密钥 scope 只说明“可使用读/写类 API”，不能代表“可读写任意 QA 资源”。租户过滤同样不能替代租户内的资源授权。

- QA 读写逻辑收敛到共享业务服务，通过 QA ID 定位所属知识库，并经统一 PermissionService 检查具体读/编辑/删除动作。
- 必须先鉴权，再修改数据、写索引或安排异步任务；拒绝时验证数据库和向量索引均无变化。
- 同时审查 `add_qa`、`add_relative_qa`、`delete_qa`、`query_qa` 等同类端点。批量读取需要权限过滤；调用方提供的 knowledge_id 必须与 QA 实际归属一致。
- `detail_qa` 与 `update_qa` 为已确认漏洞；其他端点目前属于代码审查发现的同类风险，不应在未复测前统计成已复现漏洞。

优先级：建议与服务账号权限模型修复一起作为放行前阻断项处理。

## 4. P2：PAT / 委托用户列知识空间返回 500

有实际知识空间后，`GET /api/v2/filelib/?type=3` 返回：

```text
"KnowledgeSpaceListItemResp" object has no field "user_name"
```

`knowledge/domain/services/knowledge_space_service.py` 的 `alist_mine_and_joined_cursor` 将列表项当成另一种响应模型，动态设置不存在的 `user_name` 字段。

修复：定义与开放接口契约一致的显式返回模型，在适配处构造新对象；不要修改既有 DTO 的未声明属性，也不要用允许任意字段来掩盖模型不一致。为非空列表、创建/加入合并、分页及三种主体增加契约测试。SA 的列表筛选还应复核统一 PermissionActor，不能以资源归属人的“我创建/加入”代替其授权集合。

## 5. P2：业务拒绝仍为 HTTP 200，审计结果不完整

资源访问拒绝出现 `HTTP 200 + status_code=403/18040`。`retrieve_chunks` 直接返回业务错误信封；全局 BaseErrorCode 分支也默认 HTTP 200。

修复：为 v2 建立明确的领域错误到 HTTP 状态映射；保留业务码，权限拒绝使用 403、按防枚举策略处理的对象使用 404、依赖不可用使用 503。不能将五位业务码直接用作 HTTP 状态。

同时将业务错误码写入请求审计上下文。现有审计主要读取 HTTP 状态及 `open_api_error_code`，不能可靠辨别直接返回的错误信封。SSE 已发送响应头后的业务错误需单独记录执行结果，不能仍按初始 HTTP 200 认定业务成功。v1 的既有信封兼容性单独保留。

## 6. P2：v1 会话详情可读取 SA 会话元数据

v2 跨 SA/用户/外部用户的会话读取矩阵均返回 404；但资源归属人和另一个测试用户，通过 v1 `GET /chat/info?chat_id=...` 都读到了 SA 会话标题、归属及外部主体相关字段。

本次确认的是**会话元数据泄漏**；历史接口探测返回空列表，没有据此确认正文泄漏。

修复：v1 普通读取必须解析登录用户并传入自然人 SessionSubject；已验证的分享访问继续走独立分享授权分支。禁止通过 `subject=None` 将普通请求变成不检查归属的请求。同步检查标题修改、删除、历史、附件等相邻入口，但保持既有合法分享语义。

## 7. P2：multipart 裸 user_id 被静默忽略

向 `/api/v2/knowledge/upload` 提交文件并附带表单字段 user_id，接口仍上传成功，没有返回设计要求的 `400/26019`。未观察到该字段实际替换身份；问题是已移除参数没有被明确拒绝。

原因：`_assert_no_removed_identity_input` 仅检查 query 和 application/json。

修复：对实际支持的 form-urlencoded/multipart 请求做一致的移除字段检查，复用解析结果，避免重复消费上传流；保持文件大小约束。测试 query、JSON、表单均拒绝，而正常附件上传不受影响。

## 8. P2：网关与后端错误契约不一致

- 助手 completions 缺密钥且空请求体：3001 返回 HTTP 200/业务 500；直连 7861 返回 401/26001。
- 缺密钥的 WS：直连后端拒绝握手（HTTP 403）；3001 先建立连接再以 1002 关闭。未证明匿名业务调用成功，不能将接受握手直接描述为鉴权绕过。

修复：核对 115 网关对应转发规则，优先鉴权并正确传递后端状态、响应体和 WS 拒绝结果；避免空体业务解析异常发生在鉴权之前。需用正常业务 WS 同时验证授权请求、无密钥、撤销后的关闭及代理转发行为。

## 9. 修复顺序与验证边界

1. 补齐 QA 资源鉴权及 SA 权限模型/投影，阻止越权并恢复合法授权能力。
2. 修复响应模型、HTTP/审计结果、v1 会话归属、表单身份参数与网关契约。
3. 使用保留数据进行允许/拒绝配对回归，并补真实 OpenFGA + MySQL + Redis 集成测试。

本地 `test/open_api/`：97 passed。其隔离测试不能替代真实 FGA 数据与业务资源验证，本轮实测正是在这一层发现缺口。

实际 OpenAPI 列出 40 个 v2 HTTP 路径、42 个操作；scope 注册表的 41 个操作加 whoami 已做无密钥探测。除上述网关助手空体异常外，已测无密钥 HTTP 调用返回预期拒绝。

尚未完成：真实依赖停机/网络异常注入、完整工作流及知识助手执行链路、连接建立后的实际 WS 撤销时限、跨租户/部门子树所有边界和 PAT 双层开关的真实部署切换。不能把这些项目计为实测通过。

没有修改服务器代码、配置或重启服务。本文件只提出修复方案。按用户要求，review 批次数据保留：用户 857/858、角色 244/245、SA 5、空间 4255、文件 97499、QA 库 4256、QA 47296；访问凭据在仓库外的本地私有文件中，不写入本设计补充。

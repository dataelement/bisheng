# Design：昆联 Workflow 开放接口最小接线

- Feature ID：F133
- Status：CONFIRMED / IMPLEMENTING
- Confirmed：2026-11-16，用户确认参考 SG filelib 的方式实现；本稿同步实际接线，不增加新的产品体系。
- Created：2026-11-16
- 关联：[已确认规格](./spec.md)
- 本稿为已确认技术设计，实际完成程度见 verification.md，不授权部署或环境写入。

## 1. 一句话方案

增加昆联专用 API Key 准入与用户映射层，解析出可信的本地租户和实际用户，再调用既有 Workflow 与权限服务。普通开放平台凭据、浏览器认证、版本体系和权限模型不变。不建设新管理页面。

```text
Authorization: Bearer <昆联 API Key>
  + user_account（毕昇登录账号）
  → 验证 Key 与接口能力
  → 精确账号/唯一有效成员关系反查可信租户与昆联绑定
  → 复核 Key 允许租户及当前映射/用户资格
  → 限定本次 tenant context + PermissionActor
  → 既有 Workflow / F048 服务
```

遵守 [架构宪法](../../../docs/constitution.md) C1–C6、C8；跨领域只调用 application 端口，不在端点写 ORM，不直接操作 OpenFGA。

## 1.1 SG filelib 参考核对（2026-11-16）

用户指定参考 `feat/2.5.0-sg`，本次读取本地分支快照 `132e177672c659b45789c713233aa9d9faa54133`，未切换分支，也不宣称已同步最新远端。

该分支 `open_endpoints/api/endpoints/filelib.py` 的列表通过 `get_filelib_request_user` 注入 UserPayload；对应 dependencies 的 `get_filelib_request_user` 接受 Query `external_id`，并通过 FilelibUserContextService.use_user 解析实际用户。Token 使用 `X-Developer-Token`，其 principal 与业务用户分离。写上下文传了 external_id 时，permission_user 与 record_user 都采用解析用户。

本特性借鉴三点：凭据认证与业务用户分离；统一用户依赖封装身份上下文；读写业务直接复用原服务并以实际用户鉴权/记录。不迁入整套 SG developer_token、知识库同步或其他客户功能；当前分支未发现 developer_token 源码，不能假定可直接 import 复用。

不照搬 SG 的三项行为：external_id 缺省时回退 Token 用户；按 external_id 全局查找并固定 DEFAULT_TENANT_ID；在 yield 业务期间保留 bypass_tenant_filter。昆联规格要求显式用户、获准租户与可信映射，业务执行必须退出跨租户发现作用域并固定本次真实租户。

SG 参考复用的是依赖注入模式，不原样迁移 SG Token 模块。实施采用 D-01 的窄昆联凭据元数据，避免更改单租户 service account 合同；这不是引入第二套通用开放平台。

## 2. 关键接线决定

### D-01：昆联专用凭据，不篡改单租户 service account

既有 `ApiCredential` 的主体类型、tenant_id 和 service account Owner 资格具有明确单租户含义。直接将其 principal 的 tenant_id 改成请求租户，会让校验、审计和异步快照含义不一致。

最小方案是在 open_api 领域新增独立昆联 Key 元数据表，保存哈希而非明文，拥有稳定接入方标识、允许外部租户集合、能力集合、到期/撤销状态和策略修订。复用既有安全随机生成、哈希与遮罩方法；不扩大既有凭据主体枚举，不修改其数据库约束。明文仅在签发响应展示一次。

平台超管通过普通本地认证的控制面接口管理；昆联 Key 不能管理自身。轮换保留稳定接入方标识，新旧 Key 分别保留审计记录。新增表由 SQLModel 发现机制创建；如实施发现需要改变既有表列，另列迁移任务，不在运行入口动态修改表。

这不是新建通用凭据平台，只增加现有单租户凭据无法表达的昆联集成凭据。后续若开放平台正式支持组织级集成主体，再评估合并，不现在修改所有调用方。

### D-02：专用路由入口，普通 v2 准入保持不变

正式业务前缀 `/api/v2/kunlian`，由独立聚合路由设置昆联准入依赖。它与普通 `router_rpc` 同级注册，不继承后者的 service account 准入，也不通过路径判断跳过普通 v2 鉴权。

仅专用前缀接受昆联 Key；普通 v2、v1 和其他资源入口不得接受它。独立入口安装与既有 v2 相同的错误呈现及审计要求；必须核对全局中间件是否还会提前执行旧凭据校验，不能仅 include_router 就视为接通。

### D-03：身份参数简单、单一

参考SG统一用户依赖，最新用户确认Query仅提供 `user_account`（精确毕昇user_name），GET与写操作一致；旧external_tenant_id/external_user_id Query删除并显式拒绝混传。业务JSON不混入身份，账号必填且不回退。先验证Key/能力（尚不选租户），再由User application只读发现账号唯一用户与唯一有效成员关系、sso_sync仓储反查连接下唯一绑定，最后用现有identity.resolve验证目录/投影/资格并从权威Key复核可信外部租户范围。

Key 绑定唯一可信昆联连接，连接不由调用者选择。公开账号反查后，内部仍通过连接、可信外部租户及subject核验当前目录/映射、本地用户、成员资格与租户状态；内部RequestUser/RunSubject保留这些引用，异步重验绑定原用户和租户，不以账号重名或改名迁移运行身份。不以用户名模糊匹配，不触发目录同步或自动开通。

拒绝 Cookie、旧 `X-On-Behalf-Of` / `X-End-User`、伪造本地 tenant/user 或其他身份覆盖参数，避免混合身份。秘密不进入 URL、日志、任务消息。身份标识的权威字段映射由 sso_sync application 端口封装，不能把 subject 与 member id 混用。

映射完成后只设置单个已验证业务租户上下文，退出请求必须复原；不要继承管理凭据所在租户或扩展 visible_tenant_ids 到所有获准租户。PermissionActor 来自当前真实用户事实：拒绝全局超管，租户管理员标记只允许本次租户。

### D-04：业务规则沿用，不复制浏览器端点

新端点只做协议校验与 DTO 转换；创建、元数据更新等仍在旧端点中的业务编排需提取到 Workflow application 服务，浏览器与昆联共用。禁止新端点跨 import 旧 API 端点函数，也不允许直接伪造 HTTP 请求调用浏览器入口。

版本列表、创建、读取、保存、选择编辑版本沿用 FlowService；发布/下线调用 WorkFlowService。元数据修改入口不能携带绕过发布校验的 status。首批不开放工作流删除或版本删除，不增加历史多版本同时在线；已有浏览器删除功能不改变。

授权复用 F048 当前可授予模型，不创造昆联权限包。目标用同一外部租户内的已映射昆联用户标识解析。仅修改既有服务判定可编辑的本地直接用户授权，不改保护/继承来源，不做所有者转移；撤销单条来源不等于用户最终失权。

## 3. 对外接口清单

以下是正式路径提案；字段与返回尽量复用既有 DTO，不能把旧内部模型不加裁剪直接公开。

| 方法 | `/api/v2/kunlian` 下的路径 | 既有能力 |
|---|---|---|
| GET / POST | `/workflows` | 列表 / 创建，固定类型 Workflow |
| GET / PATCH | `/workflows/{workflow_id}` | 详情 / 元数据修改 |
| GET / POST | `/workflows/{workflow_id}/versions` | 版本列表 / 创建版本 |
| GET / PUT | `/workflows/{workflow_id}/versions/{version_id}` | 版本详情与图 / 保存 |
| POST | `/workflows/{workflow_id}/versions/{version_id}/select` | 选择编辑版本，不等于发布 |
| POST | `/workflows/{workflow_id}/publish` | 发布指定版本 |
| POST | `/workflows/{workflow_id}/unpublish` | 下线，复核预期版本 |
| GET | `/workflows/{workflow_id}/permissions` | 授权记录及当前可授予模型 |
| GET | `/workflows/{workflow_id}/my-permissions` | 实际用户当前动作 |
| POST | `/workflows/{workflow_id}/permissions/grants` | 授权指定外部用户和现有 model_key |
| POST | `/workflows/{workflow_id}/permissions/grants/{assignee_id}/revoke` | 撤销可编辑直接授权 |
| POST | `/workflow-runs` | 启动，返回 session_id |
| GET | `/workflow-runs/{session_id}` | 状态、结果、等待输入表单 |
| POST | `/workflow-runs/{session_id}/cancel` | 取消受理/确认 |
| POST | `/workflow-runs/{session_id}/interactions/{interaction_id}/submit` | 人工输入与恢复 |

不新增独立的 Schema 管理体系：发布版本的输入输出定义随其详情提供。列表沿用既有游标分页。事件流和登记快照/变化同步本期不新增公开接口。

控制面前缀 `/api/v1/identity-integrations/kunlian/api-keys`：POST 签发、GET 列表、PATCH 修改范围/到期、POST `/{key_id}/revoke`、POST `/{key_id}/rotate`。仅全局超管，列表只展示遮罩。轮换同一事务建立新 Key 并撤销旧 Key，响应丢失不重显旧明文，可重新轮换。

Key 能力为 read、write、publish、invoke、grant 五类，不隐含授予资源权限。每条端点显式绑定能力，未声明默认拒绝。

## 4. 执行接线与现有缺口

复用 F122/F123/F127 的会话、版本冻结、幂等、交互和取消机制，绑定真实身份、正式 Worker 和补偿装配，不新造运行引擎。

启动允许省略 workflow_version_id：首次受理时原子选择当前有效发布版本；若明确传版本，则必须是当前有效发布版。新请求不能启动已被替换的历史版本。已有幂等会话优先查回，不能因当前版本变化而重启或换版本；摘要必须区分调用者显式版本与“选择当前”意图。受理后冻结图及版本，后续发布不改变原运行。

必须处理的代码缺口：现有候选运行依赖 F121 登记 AVAILABLE，并只支持经验证的有限文本输入输出，不能直接宣传为任意 Workflow 都可运行。本次不要求昆联登记同步：正式受理应从现有发布事实准备冻结图，复用现有输入输出解析与校验；将“是否允许调用”的依据与 Mock 登记依赖解耦。对现有执行器无法支持的输入形态应在受理前明确拒绝，不能受理后无声降级。实施任务必须覆盖现有常用输入/输出及人工输入链路，并在调用说明列出真实支持范围；若需要突破现有执行器能力，须单列范围确认，不借接线顺带重造引擎。

运行归属使用稳定接入方、可信租户及用户，轮换不改变归属。每次后续请求重新核验当前 Key 与实际用户资格。Worker 持久引用原启动凭据及策略事实，不保存秘密。原 Key 撤销会阻断该 Key 下尚未推进的工作；新 Key 可按当前资格查询/取消仍存在的旧运行，但不自动复活已终结任务。这样轮换可接续操作，不绕过已确认的撤销停止规则。

## 5. 一致性、安全与运行规则

- Key 与允许范围从权威库读取，不增加正向认证缓存；撤销提交后开始准入校验的新请求必须看到失效。已通过校验的并发写入不能被追溯回滚；发布、授权等提交前复核资格，运行在领取/恢复/节点推进边界复核。外部进行中节点仅尽力停止。
- 2026-11-16用户确认移除所有正式昆联接口的客户端Idempotency-Key。端点每次HTTP生成新的随机内部操作引用（UUID），交给既有创建/运行/答案/授权服务维持内部台账与投递保护，不读取客户端同名头；内部方法和候选接口原合同保留。重复创建/启动不是查回请求，可能产生新资源/运行；答案由交互状态原子消费，授权仍按当前修订判定。If-Match不变，不按body哈希猜测两个相同业务请求是否同一次操作。
- 授权投影未FINALIZED返回待确认；正式HTTP不再提供客户端键查回合同，operation_ref保留供受控核对。内部SQL回执与F048 ledger仍保留，不能因删除对外参数移除持久事务保护。
- 统一 `status_code/status_message/data`，使用真实 HTTP 状态；缺 Key 401，范围/资格拒绝403，无权资源按既有隐藏规则404，修订/幂等冲突409，输入不符422，依赖不可确认503，限流429。错误码沿原 Owner 分配，设计不抢占未核对号段。
- 敏感字段显式裁剪：不得返回 Key、令牌、存储秘密或节点凭据。允许读取完整图须具备既有编辑级读取资格，不把可见权限等同于可读编辑图。
- 写操作在业务执行前持久记录最小审计意图，失败则拒绝；后续审计结果写入失败必须保留可补偿事实并告警，不把已提交操作报告为未执行。认证失败仅记录安全分类和请求关联，不能为了审计保存未知 Key 原文。
- 复用已有 API 限流机制，按 Key 汇总，再按租户/用户限定执行并发；具体阈值与保留期限沿既有正式运行策略，代码缺失时在 tasks 明确建立有界默认值，不能使用测试时钟常量直接充作生产策略。
- 平台处置复用现有运维/管理授权，不给昆联 Key 开管理员旁路；未授权不实施环境写入。

## 6. 文件职责与需求追溯

| 位置（新文件为拟新增） | 职责 | 需求 |
|---|---|---|
| `open_api/domain/{models,repositories,services}/kunlian_credential.py` | Key 元数据、哈希校验、生命周期与范围 | REQ-01、REQ-09 |
| `open_api/application/kunlian_access.py` | 可信集成身份/能力端口及上下文生命周期，不滥用单租户 principal | REQ-01、REQ-02、REQ-03 |
| `open_api/api/endpoints/kunlian_credentials.py` | 平台超管控制面 | REQ-01 |
| `sso_sync/application/kunlian_identity.py` | 只读映射与当前资格；由原 Owner 查询，不自动开通 | REQ-02、REQ-03 |
| `workflow/application/kunlian_workflow_management.py` 及窄写入适配 | 共用列表/创建/版本/发布服务，必要的端点业务下沉 | REQ-04、REQ-05、REQ-06 |
| `open_endpoints/api/endpoints/kunlian_workflow_management.py` | 正式管理协议，严格身份/业务DTO分离 | REQ-04、REQ-05、REQ-06 |
| `open_endpoints/api/endpoints/kunlian_workflow_api.py` 与 `workflow/application/{kunlian_runtime,kunlian_permission_api}.py` | 正式聚合端点接入运行和授权；既有候选端点保留测试兼容，不挂载其占位依赖 | REQ-07、REQ-08 |
| `api/router.py`、`main.py` 及全局准入相关位置 | 独立专用路由装配、错误与中间件兼容检查 | REQ-10 |
| `worker/workflow/`、运行仓储/策略和权限持久回执 | 正式投递/补偿、失权阻断、轮换审计 | REQ-07、REQ-08、REQ-09 |
| `test/open_api/`、`test/workflow/`、`test/sso/`、调用说明 | 负向权限、正式接线与交付证据 | REQ-01～REQ-10 |

新表按模型发现规则登记；现有运行材料能承载凭据引用时不改表。只有确实需要索引或字段变化才生成独立 schema migration，不写数据回填。API 层跨模块仅依赖 application 导出，不能从专用路由 import 另一模块 endpoint。

## 7. 最低充分验证与发布边界

1. 凭据/映射集成：两个允许租户、一个不允许租户；普通用户、租户管理员、全局超管；Key管理资格、失效与轮换（AC-01～AC-07、AC-18、AC-20、AC-21）。
2. 管理写入闭环：创建—保存版本—发布—执行—下线；并发修订、业务失败回滚与敏感字段（AC-08～AC-11、AC-17）。
3. 运行/授权闭环：人工输入恢复、取消、失权阻断、持久授权查回与授权后真实访问；独立 Worker，不能只覆盖依赖注入测试应用（AC-12～AC-16、AC-21、AC-22）。
4. 普通开放平台与浏览器回归；MySQL/DM8并发和真实权限运行时证据单独记录，不以SQLite冒充；真实昆联环境未授权或不可用则 NOT_RUN（AC-18、AC-19）。

新能力默认无可用 Key，只有平台超管显式签发后能调用；普通入口仍保留旧行为。回退先停止新准入、处置存量运行，再停专用接线，不删除运行、授权或审计事实。

## 8. 实施快照与剩余门禁

已按用户确认的 SG 方式写入正式路由、Key控制面、用户依赖、业务服务、Worker和15秒有界补偿；本地联合回归205 passed。凭据与授权回执各新增一张窄表，审计复用既有AuditLog；未修改现有表列、未部署、未签发真实Key。正式main只读import已确认33条昆联相关路由（含既有7条、Key6条、新业务20条），未执行lifespan或访问真实服务。

正式执行已解除旧候选四节点限制，支持文本协议下核心Workflow节点；真实LLMNode+GraphEngine经外部模型替身验证。平台Agent/平台知识节点、多输入/多输出、附件/非文本协议仍在受理前拒绝，人工输入恢复仅start直接到输入节点；不宣传任意图全面可用。原Key撤销后新Key可查/取消旧run，不再受理其等待恢复。

公开输入输出定义经 GET `/workflows/{workflow_id}/schema` 返回，使用当前有效发布资料，无需暴露编辑图。元数据与版本响应按白名单裁剪，草稿If-Match使用正式事务而非Mock开关。

资源门禁已接：每Key默认120次/60秒，按接入方/租户/用户跨workflow活跃上限5，以User→成员→Flow锁串行化新受理；可调排队120/执行300/等待900/保留86400秒。过期正式终态payload通过有界keyset清理，保留归属与永久幂等墓碑，已净化记录不再UPDATE但历史扫描成本仍存在。最终本地联合375 passed、2项缺redis-server跳过。运行查询的失败文本仅允许稳定分类，取消回执明确区分受理、确认与原终态。

剩余门禁：受控处置/审计补偿的真实流程、真实权限及独立Broker/Worker、Python3.11及MySQL/DM8、真实昆联验收。局部通过不代表全特性已交付；参见verification。


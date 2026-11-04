# Design：F115 应用运行信息、审批当前可见范围与知识库创建

**关联**：[已确认 spec](./spec.md) · [已确认 discovery](./discovery.md)。\
**版本**：v3.0.0；发版线 `feat/3.0.0`。\
**最后更新**：2026-11-02。\
**状态**：用户于 2026-11-02 单独确认设计；代码与本地定向验证已实现，真实部署 E2E 尚未执行；52 条规格已确认。本文区分固定基线现状、实施接线和远端部署，不将方案写成已部署事实。\
**源码基线**：`497256d289793ce016df07cf8ab38f32988faca4`，工作分支 `codex/vibe-runtime-review-20261102`。116/120 只读环境证据沿 discovery，不在设计阶段更新环境。

## 1. 目标与非目标

补齐当前实例可观测事实，明确模型调用用户筛选空态，在原审批阅读资格内显示当前有效访问授权，并统一本租管的新建知识库资格。沿用现有运行、权限、审批和知识库领域，不新增并列授权规则。

非目标沿 spec：不增加监控系统、不恢复 v1 控制、不改现有应用的 OBO 接线、不回填审计或历史审批、不迁移资源、不补写角色菜单和授权；知识库复制、发布审读/预览及其它平台能力不扩权。

## 2. 关键约束

遵循 [constitution C1–C8](../../../docs/constitution.md)、[release-contract](../release-contract.md) 和前后端各自 AGENTS；全局铁律不在本文重抄。

- **两个时间面**：版本、发布说明、声明及审批决定属于冻结内容；可见范围是本次查询的当前授权，只作只读装饰，不写入历史快照。
- **当前执行体**：必须同时匹配应用、节点、操作和执行引用；K8s 额外校验 Pod UID，不能按名称猜测或选第一个容器。
- **只读观测**：复用 v2 执行器现有观察和应用探活；Docker 保持现有单次 HTTP 探活的 2 秒超时及判定口径，不增加后台任务、定时器或全新探活请求入口。
- **完整性优先**：只有完整授权与对象资格查询成功才能产生 `owner_only=true`。投影不就绪、目录服务失败、结果超过本次可完整读取的界限均返回显式不可确认，不输出未经确认的部分名单。
- **有界读取**：权限来源按既有 500 条游标页读取，本次摘要最多检查 5,000 条来源、最多 5 秒；任一界限触发则整体 `unavailable`，不把截断后的剩余对象当作不存在。该预算仅用于当前摘要，不改变 F048 通用完整授权目录。目录批量解析，不逐成员展开。
- **创建资格不等于管理视角**：新资源仍落实际自然人与其当前所属租户。新建表单固定打开时的所属租户，实际写入前重验，管理视角不会覆盖此值。
- 不新增数据库表或列、配置顶层键、队列、权限动作、运行协议版本或监控依赖。MySQL/DM8 通过既有持久层与 dialect helpers 保持兼容。

## 3. 方案对比与选定

### D1. 用现有执行器观测补齐运行事实

- **备选**：只转发 Docker 原生 Health；从历史 AppInstance 补字段；新建定时采样系统；复用现有执行器观察并统一只读状态返回。
- **选定**：最后一种。在 Docker/K8s `observe` 的结果中补充当前应用容器的计数、启动时间和探活状态；v2 只读状态端点统一转换，后端仅保留公开字段。
- **原因**：116 的容器有实际启动时间但未设置原生 HEALTHCHECK；基线状态端点漏转时间，而执行器已有实际 HTTP/Ready 观察。历史 AppInstance 回退可能把旧实例信息当成当前值；新增采样系统超出 D1。
- **重新考虑条件**：后续明确要求长期监控、历史趋势或改变现有探活判定时，另立需求，不借本次显示修复改变发布就绪门槛。

### D2. 模型用户查询保持原合同，只补空态与范围切换

- **备选**：用负责人补用户；返回全租户人员；新增历史回填；保持真实记录查询并修前端状态。
- **选定**：保留现有候选和记录接口、范围校验、分页及真实 `user/natural_person` 过滤；使用现有共享 Select 的 `emptyText/noMatchText/loadingText`，在业务层区分失败和重试。
- **原因**：116/120 当前无应用限制时已返回真实用户候选，截图应用只有应用自身调用；未复现候选接口整体为空。补负责人会改变历史身份事实。现有 Select 已具备相应文案入口，无需改共享控件或候选数据结构。
- **重新考虑条件**：后续需要真实用户姓名快照、更多身份筛选或新的 OBO 数据采集，单独评估来源和历史兼容；不由本功能推测。

### D3. 审批校验之后添加当前摘要，不覆盖冻结快照

- **备选**：重建 `detail_snapshot`；让客户端调用通用授权列表；为审批人临时赋 `manage_permission`；在原详情读取通过后添加独立的 `current_visibility`。
- **选定**：最后一种。审批服务先完成原阅读校验，再经现有场景 Handler 工厂调用应用发布场景的只读补充方法；其它场景不增加业务行为。新字段与两个历史 snapshot 同级。
- **原因**：基线任务、个人实例及管理实例详情均直接返回保存的 snapshot。直接覆盖会让冻结内容与当前事实混淆；通用授权列表要求长期 `manage_permission`，不适合已确认的窄审批例外。
- **重新考虑条件**：另有场景提出相同的动态展示需求后再评估共性。本次只增加一个可选场景补充钩子，不建立新的审批视图框架。

### D4. 当前范围读取 F048 有效动作来源，身份目录由业务侧补充

- **备选**：按 model 名称/level 判断；业务侧查询 Grant/OpenFGA；枚举全租户每个人做 Check；由 F048 提供可信服务端有效动作来源读取，再批量核对对象资格。
- **选定**：最后一种。权限应用端口提供目标资源 `use` 的有效来源；复用 CURRENT Catalog、当前投影和继承规则。现有租户主体目录新增批量只读解析，返回有效、已失效、不可确认三类结果和显示名称。
- **原因**：已有可信服务端 `list_effective_direct_user_ids_by_model` 说明来源读取不必借管理页身份，但它只支持直接人员和指定模型，不能直接满足本功能。通用 `list_grants` 的管理门禁保持；新增窄读取不提供 HTTP 入口、不伪造 owner/超管。
- **重新考虑条件**：权限模块正式提供同等语义的完整 action 来源公共协议时改用该协议；不保留两套来源判定算法。

### D5. 仅放开知识库新建，不修改全局创建菜单

- **备选**：给租管批量加菜单；将 `create_knowledge` 全局并入租管菜单；仅改按钮；知识库新建使用独立资格策略并复用原创建流程。
- **选定**：最后一种。前端区分 `canCreateLibrary` 与 `canCopyLibrary`；后端 Web 新建入口执行本功能的创建资格策略，复制仍保留原菜单及源资源读取门禁。
- **原因**：两类知识库页面当前将新建资格复用于复制；后端 create/copy 都要求原菜单。单改页面或全局加菜单会分别导致继续拒绝或顺带扩大复制权限。
- **重新考虑条件**：以后明确要求统一所有资源的创建/复制能力时再做菜单策略调整，不把本次例外推广到其它资源。

### D6. 复用真实 Web 身份校验，并把表单租户作为前置条件

- **备选**：信任登录响应的 `is_child_admin`；按页面选中管理租户写入；修改共用 KnowledgeCreate 的所有调用者；Web 新建请求携带表单预期租户，服务端按当前真实身份检查。
- **选定**：最后一种。仅 Web create 请求增加可选 `expected_tenant_id`；两个新建对话框均固定发送打开时的 `leaf_tenant_id`。服务器不把该参数当作目标租户，只用于与已验证所属租户比较；写入者仍为真实登录自然人。
- **原因**：JWT/表单可能跨越人员迁租户和资格变化，页面管理视角又不同于人员归属。已有 `user.application.runtime_identity.resolve_web_runtime_identity` 可验证多租户下的人员、唯一有效租户及会话版本；新建用途在同一应用模块增加薄入口处理单租户，不改延迟运行任务原有严格合同，不新增身份系统。
- **兼容**：旧请求缺少该字段时，以其经验证 JWT 租户作预期值，仍须与实时身份匹配；新页面显式固定预期值，可拒绝表单打开后换会话/换租户的提交。共享知识库请求及开放 API 不因此新增菜单门禁。
- **重新考虑条件**：未来正式支持跨租户代创建，须另审创建归属和防陈旧合同，不能放宽此处比较。

## 4. 固定基线与本地实施接线

### 4.1 固定基线现状

| 链路 | 497256d28 的真实接线 | 缺口 |
| --- | --- | --- |
| 运行状态 | `app_query_service.get_instance` → `orchestrator_client.status` → v2 `platform_observe.status` → 当前绑定检查 | Docker 只读原生 Health；两形态漏启动时间；缺失计数默认零；后端找不到执行体时回退旧 AppInstance |
| Docker/K8s 观察 | `executors/docker.py::observe` 已发单次应用探活；`executors/kubernetes.py::_observed` 已核对 Pod Ready 与 EndpointSlice UID/IP | 返回未覆盖完整显示事实；K8s 找不到 app 状态时求和为零 |
| 模型用户候选 | `runtime_audit_query_service.candidates` → `runtime_audit_repository.statement/candidates`；API `candidates/visitor?kind=model` | 数据范围与真实身份过滤已存在；Select 使用通用空文案，失败提示与空列表可能同时出现 |
| 审批详情 | `approval_center_service.get_task_detail/get_instance_detail` 先校验资格，再返回 `detail_snapshot/payload_snapshot`；app Handler 仅复制空的 `visibility_snapshot` | 缺当前授权展示，客户端仅解析冻结 snapshot |
| 权限来源 | `F048ResourcePermissionApi.list_grants` 和 runtime `list_permission_sources_page` 要求 manage_permission；`control_state.load_source_page` 处理 CUSTOM/INHERIT 与 CURRENT 来源 | 不能让普通审批阅读者直接调用通用 roster；无按 action 返回当前人员/组/部门摘要的端口 |
| 对象目录 | `TenantPermissionSubjectDirectory.canonical_source/display_names` 已验证或显示对象 | 现有人员 canonical 校验关注有效成员，不能直接当作“人员未停用且名称完整”的完整摘要证明 |
| 知识库 | `knowledge.create_knowledge` 先断言菜单，再调用同步创建；Doc/QA 两页面相同条件控制新建和复制 | 租管路由可见与新建资格不一致；表单没有固定创建租户前置条件 |

基线注释中的历史 owner-only 或长期 v1 说明不能覆盖 F114 当前合同。`orchestrator_client.status` 中仍出现 `/v1/` 字符串，但 `_request/_v2_request` 强制 v2 并改写路径，不能据此重新接通 v1。

### 4.2 运行状态：沿当前绑定观察

`发布页既有实例查询 → 原 F114 状态阅读门禁 → 后端只读状态 RPC → 当前绑定校验 → 执行器 observe → 统一事实 → 显示`。

1. `platform_observe.status` 只读加载当前 `app_id/generation/operation_id/exec_ref/node_id`。Docker 校验 app、操作、节点及 v2 管理标签；K8s 校验应用、操作、节点、Pod UID 和应用容器名 `app`。
2. 将显示所需事实补入执行器观察结果。Docker 从同次精确容器 inspect 取得 `State.StartedAt` 和 `RestartCount`，健康仍由已有应用 HTTP 探活形成；原生 Health 可作诊断，不能替代统一的应用就绪语义。K8s 仅从匹配 `app` 的 `containerStatuses` 取得重启与当前 `state.running.startedAt`，当前状态为 terminated 时可取其 `startedAt`；不读 initContainer 或 `lastState` 冒充当前。
3. `observe` 原 `ready/running/target` 语义供生命周期继续使用；新增 `probe_state` 区分已成功、已失败、尚无结果，不改变原 `<500` 的 HTTP 判定和发布就绪规则。探活返回失败和探活基础设施不可访问是不同结果；无应用地址、状态缺失不得默认为探活成功。
4. 状态返回前再次确认绑定的 generation、operation、exec_ref（K8s 含 UID）未变化；变化则报告暂不可确认，刷新再读，不能混合新旧事实。不修改平台绑定或尝试自愈。
5. Docker `Restarting`、K8s Pending/ContainerCreating 或当前操作 `starting` 且没有完成判定时显示启动中。已有明确探活失败则为异常；Ready/探活成功为正常；缺少有效判定为未知。执行体已停止时 phase 为 stopped，不显示仍健康。
6. 无绑定与绑定的执行体丢失是正常可解释的两种只读结果，见 §4.5。调用错误、归属不匹配、平台/集群不可用走原 16121 故障链。后端 `get_instance` 不再用旧 AppInstance 的健康、计数、启动时间补“当前值”。
7. 启动时间统一输出带时区的 ISO-8601 UTC；空值、Docker 未启动零日期、无效时间为 null。计数只有明确的非负整数才有效，布尔/缺失/非法值为 null；真实 0 保留。前端先验证时间，再复用 `displayTimestamp.formatTimestamp` 转浏览器本地时区，不改全局时间工具。

### 4.3 访问用户：只改状态与查询范围生命周期

`当前具体租户与筛选条件 → 原候选 API → 真实自然人记录候选 → 选择后原记录 API`。

- `CandidateFilter` 继续通过 `controllers/API/runtimeAudit.ts` 获取候选，不新增数据库查询、候选字段或历史身份来源。
- 空搜索 + 查询成功 + 空候选：显示“当前范围没有访问用户记录；应用自身调用不代表自然人访问”。有搜索 + 成功空候选：显示无匹配用户。加载中使用 Select loading；失败时使用失败文案和重试按钮，空提示不得同时宣称无记录。
- `emptyText/noMatchText/loadingText` 覆盖该过滤器，不改变共享 Select；真实 ID 原样用于过滤，不把 app/self ID 转成人名。
- kind/具体租户/应用/时间等范围变化后重置该过滤器搜索与不再适用的 visitor 选择；请求 key 含完整新范围，不使用旧范围 placeholder 数据。读取途中切换范围的旧响应只能留在旧 key，不回写新状态。
- 候选继续使用后端的同一授权范围及其它过滤条件；访客候选无需扩展成全租户人员。保留现有分页，列表和导出仍使用原冻结筛选合同。

### 4.4 审批摘要：先取得阅读资格，再读取当前授权

`个人任务/个人申请/管理详情 → 原审批阅读校验 → app 发布 Handler 只读补充 → 业务核对 app/tenant → F048 action 来源 → 业务目录核对 → current_visibility`。

#### A. 原阅读门禁与绑定

- 在 `get_task_detail`、`get_instance_detail` 的原租户、任务/申请归属或管理资格检查**之后**调用补充方法。失败的原鉴权不得进入补充逻辑，不能用 `app.publish` 代替审批阅读资格。
- 通过 `approval_runtime_handler_factory` 为 app 场景取得新 Handler，调用新增可选 `read_current_detail`；无此方法的其它场景不增加任何查询。注册和调用均在服务层，不在 endpoint 跨模块导入。
- 审批模块创建进程内的已验证阅读上下文，包含 instance、scenario、tenant、business_resource_id、当前阅读者和读取用途；不是 HTTP 可提交的对象，不存储凭据，不注册新对外 endpoint。
- 发布场景的新增 `app_publish_current_visibility_service.py` 从该上下文取得应用 ID，核对保存的业务资源绑定及当前应用租户；若 payload 存在 app_id，必须与业务绑定一致。审批申请人、客户端传的 app_id 或历史 owner 名称不能替代绑定检查。
- 正常目标由 app 业务适配器生成 `VerifiedPermissionTarget`；不伪造负责人或超管 actor。个人审批沿所属租户；管理详情仅允许已通过原管理门禁的具体租户。应用删除单独映射为 deleted；跨租户/绑定不一致不返回对象名单。

#### B. F048 的窄只读来源端口

- 在 `permission.application` 增加 `read_effective_action_sources(target, action)` 的可信服务端端口，内部委派 F048 runtime。它不替调用方判断审批资格，不接受客户端“已授权”标记；仅供已验证业务目标和前置业务阅读资格后的服务端调用，首个调用点限定为上段应用发布补充服务。
- 复用 runtime 当前 Catalog/Store/model pin、`_require_current_target` 和权限内部 `load_source_page`；选取当前有效且 `action_codes` 含 `use` 的模型，不按名称或 level 推断。每页读取在权限持久层完成，业务方不查询 Grant 或 OpenFGA。
- CUSTOM 取本地有效来源；INHERIT 复用既有最近自定义祖先来源与本资源受保护创建者语义，不引入第二套继承逻辑。目前 app 固定 CUSTOM，仍为可复用端口保留现有继承合同的配对验证。
- 必须验证目标及实际涉及祖先投影 CURRENT、版本一致，并在完整分页结束后复核版本与 Catalog 未变化。PROJECTING/FAILED_CLOSED、游标不前进、未知模型或不完整来源均不能变成完整空集合；超预算返回不可确认。
- 通用 `list_grants/list_permission_sources_page` 的 `manage_permission` 保持原样。新端口不包含授权写入、完整 model/Grant 元数据、编辑能力或来源秘密，不提供给通用 HTTP roster 使用。

#### C. 名称与有效资格

- 经现有 `get_grant_subject_directory` 取得业务侧目录，由 `TenantPermissionSubjectDirectory` 增加批量只读解析方法。新增 SQL 只放所属领域 Repository，权限模块仅依赖应用协议，不导入用户/部门/应用 ORM。
- 多租户开启时人员必须未停用且只有一个有效当前人员租户，与应用租户一致；关闭时按有效自然人/tenant=1 语义验证，不要求额外成员行。user 应用模块提供批量 `read_current_person_facts(user_ids)`，只输出当前人员事实，不要求也不制造这些人员的会话；Web 创建身份入口复用这些事实并额外验证真实会话。已明确失效的人员来源排除。部门/组需确认仍存在且属于该租户；批量读取失败、人员所属不能唯一确定或无法确认名称时，整个摘要 unavailable。
- 组与部门保留 userset 含义：部门可注明含下级，用户组可注明仅管理员；不展开成员，也不承诺组内每个人都可以访问。按 `(type,id,userset_relation,include_children)` 去重，不重复同一来源的显示。
- 服务账号来源跳过普通访问人员列表；管理员隐式访问只显示统一说明。发现当前合同之外、不能用人员/部门/组准确表达的有效来源（如历史 tenant 来源）时不得丢弃后宣称 owner-only，返回不可确认并记录安全原因。
- 负责人当前资格使用真实当前人员和 F048 `use` 判定，不仅看 protected creator 行或历史快照；该人员失效则不补列“负责人可见”。构造其 PermissionActor 时只使用该人员当前有效成员、真实全局/租户管理员事实（原身份应用入口及 `is_tenant_admin` 查询），不调用可能返回当前请求阅读者缓存的 `resolve_permission_actor` 来代验另一人；也不临时给予管理员字段。单独查询负责人事实不等于代其执行业务。有效 owner 若不在普通来源列表则仅为展示去重补入，不补写授权。
- 全部成功后才计算 owner_only：负责人有效，且不存在负责人以外的有效普通访问对象。完整成功但负责人无资格且无其它对象显示“当前没有有效普通访问对象”。

#### D. 失败隔离与页面

- `detail_snapshot/payload_snapshot` 原样返回；当前摘要是独立字段。过往空占位不回填，后续新审批也不把当前范围写入冻结快照。
- 只读补充是明确的非关键展示步骤：其内部依赖异常记录完整服务端异常并返回 sanitized unavailable，不吞成成功空名单；原阅读鉴权和场景绑定检查不放进该降级捕获。未知程序异常同样留错误日志，前端看到不可确认，不泄露异常正文。
- 客户端 `api/approval.ts` 扩展详情类型，`AppPublishDetailPanel` 只从 `current_visibility` 读取该区域，其余区域继续读 `detail_snapshot`；字段缺失的旧服务端显示“暂不可确认”，不回退旧快照冒充当前。
- 打开详情重新查询，提供当前详情刷新回调；终态也读当前摘要。平台异常列表已有管理详情在 `ExceptionPanel/useApprovalExceptions` 中缓存，补充只读区域并在展开/刷新时重读当前管理详情，缓存按具体租户与 instance 隔离，不将终态缓存永久视作当前。
- client/platform 各自使用本应用 API 包装与组件组合，不跨 SPA 复制状态或直接导入另一应用组件。平台只新增小型摘要区域，不复制整个客户端审批卡。

### 4.5 关键对外字段

#### 实例状态（原 `GET /api/v1/apps/{app_id}/instance`，新增/收窄字段含义）

```json
{
  "instance_id": "current-execution-ref",
  "phase": "running",
  "health": "healthy",
  "restart_count": 0,
  "started_at": "2026-10-30T10:33:15.363Z",
  "last_probe_at": "2026-11-02T02:00:00Z",
  "observation_state": "current"
}
```

| 字段 | 类型与约束 | 消费规则 |
| --- | --- | --- |
| `phase` | 沿既有 pending/building/starting/running/unhealthy/stopped/failed | 应用业务状态不由此改变；观察失败不伪装已删除 |
| `health` | healthy / unhealthy / starting / null | null 显示未知；非法旧值也显示未知，不原样露英文 |
| `restart_count` | 非负整数或 null | 类型改为 nullable；禁止 `?? 0` |
| `started_at/last_probe_at` | 带时区 ISO-8601 或 null | 无有效值显示未知/尚未启动；不输出零日期或用当前查询时刻冒充启动时间 |
| `observation_state` | current / no_execution / execution_missing | no_execution：无绑定，phase stopped、instance_id null、三项事实 null；execution_missing：绑定有引用但执行体丢失，phase unhealthy、保留引用、事实 null。真正依赖故障返回错误 |

manager `/v2/apps/{app_id}/status` 使用相同语义，保留内部 app/generation 信息，后端白名单只增 observation_state。AppNotFound 回退不再读取旧实例事实；新 manager 对“无执行体”给出上述明确结果，旧 manager 的模糊 404 只显示无法确认，不能恢复历史事实。旧服务端缺少 observation_state 时新前端将三项事实作为尚未确认的新合同信息显示未知，不把旧默认零值或历史回退当作已验证当前事实；应用业务状态仍独立显示。

#### 审批详情的同级增量

```json
{
  "current_visibility": {
    "state": "available",
    "checked_at": "2026-11-02T02:00:00Z",
    "owner_only": false,
    "owner": {"id": "849", "name": "负责人示例", "eligible": true},
    "subjects": [
      {"type": "user", "id": "849", "name": "负责人示例"},
      {"type": "department", "id": "60", "name": "部门示例", "userset_relation": "subtree_member", "include_children": true},
      {"type": "user_group", "id": "12", "name": "用户组示例", "userset_relation": "admin", "include_children": false}
    ],
    "admin_implicit_access": true,
    "reason": null
  }
}
```

- `state=available` 仅代表完整确认；owner_only 为布尔。`owner` 是当前负责人信息，不能从冻结名称推断有效资格。
- `state=deleted|unavailable` 时 `owner_only=null`、`owner=null`、`subjects=[]`；空数组不能在前端解释成仅负责人。reason 仅为固定安全值：application_deleted、application_unavailable、authorization_unavailable；不返回 SQL、FGA 响应或身份目录详情。
- 新前端始终提示“当前可见范围，授权变更即时生效，不影响审批”及管理员隐式资格说明。已有审批同意/拒绝按钮、审读及预览入口继续遵循原能力，不由当前摘要推导。
- JSON 示例只是结构示意，不包含真实凭据或对示例 ID 的权限承诺。

#### 其它接口

- `GET /api/v1/app-runtime-audit/candidates/visitor?kind=model`：请求/响应不变，仍为 `items[{id,label,deleted_or_revoked}],has_more`；记录与导出合同不变。
- `POST /api/v1/knowledge/create`：Web 专用请求在既有字段外增加可选正整数 `expected_tenant_id`。它不是落库字段，不接受由此指定任意租户；Doc/QA 两对话框均发送打开时的所属租户。
- 三个审批详情入口：`/api/v1/approval/my-tasks/{task_id}`、`/api/v1/approval/instances/{instance_id}`、`/api/v1/approval/admin/instances/{instance_id}` 只增加同级字段，不改原 snapshot；已核对 `approval_user.py` 的 router 与路径，不新设别名。

### 4.6 知识库新建接线与写入前重验

`Doc/QA 表单固定所属租户 → Web create endpoint → 当前 Web 身份/创建资格 → 原校验 → 写入前再验 → 原创建/投影/索引流程`。

1. 新增 `knowledge_creation_policy.py`，作为 Web 新建专用领域资格策略，消费真实登录会话的服务器引用，并调用 `user.application.runtime_identity` 新增的 `resolve_web_creation_identity` 薄入口。多租户开启时复用既有 `resolve_web_runtime_identity` 的唯一有效成员与租户校验；关闭时由同一 user 应用模块按有效人员、会话期限及 token_version 验证并固定 tenant=1，不要求旧单租户人员凭空补一条 UserTenant。新增读取仍在 user 所属 Repository，不放业务 SQL 到策略服务。最后比较 expected/JWT/实时所属租户；身份不确定、租户停用或会话失效按原身份错误拒绝，既有 runtime 身份函数语义不改。
2. 同一真实自然人需具备以下之一：原有效超管/创建菜单资格；或当前经 `permission.application.is_tenant_admin` 确认的本租户管理员资格。部门管理员和界面 is_child_admin 不成为后端授权来源。依赖故障不能静默授予租管例外。
3. 新建资格传递的是服务端创建的短生命周期上下文（人员/所属租户/会话版本/预期租户），不是持久对象或客户端 capability。endpoint 调用已有异步 `KnowledgeService.acreate_knowledge`，仅 Web 路径携带此上下文。
4. 原名称、embedding、租户与其它输入检查后，在 `acreate_knowledge` 进入 `acreate_knowledge_base` 之前重验该上下文和当前资格。失败时没有业务行、索引、FGA Grant 或后续任务。开放 API/其它内部调用不携带该 Web 上下文，继续原通道资格，不能被新增菜单检查误拦。
5. 整个 Web 创建使用既有 `tenant_execution_scope(verified_tenant)` 配合 `strict_tenant_filter()`，退出即恢复 ContextVar，不能把它误写成接受 tenant 参数的 strict 过滤函数。用户 ID 与租户 ID 仍由服务器覆盖为已验证自然人及其所属租户；客户端 user_id、管理范围和预期租户不能成为写入 authority。继续原创建者投影、失败补偿、索引初始化和审计；不添加菜单或角色。
6. 前端页面 `canCreateLibrary=原有菜单/超管资格 OR 当前 is_child_admin`；`canCopyLibrary=原有菜单/超管资格`，再叠加现有源读取条件。表单在打开时固定当前 `leaf_tenant_id`，不是 `useAdminScope` 的租户；该值尚未加载时不提交，刷新身份信息，只有服务端确认单租户模式时才固定 1。资格变化时按钮可能等待用户信息刷新，但实际写入始终拒绝过期资格。
7. expected 与当前所属租户不一致使用 §6 的专用前置条件错误，提示刷新表单；不要误用管理视角错误或悄悄改写到新租户。

### 4.7 模块职责与影响面

| 现有/拟新增模块 | 做什么 | 不做什么 |
| --- | --- | --- |
| runtime-manager `executors/*`、`api/platform_observe.py` | 精确执行体观察、nullable 事实及统一状态 | 不恢复控制 v1、不触发修复、不持久化第二份应用主数据 |
| backend `app_query_service.py`、`orchestrator_client.py` | 原阅读门禁、公开字段、区分故障和无执行体 | 不调用 Docker/K8s SDK、不回填旧实例值 |
| platform `PublishTab`、`hostedApp.ts` | 状态、未知、零与有效时间展示 | 不按 UI 猜测健康、不改变全局时间语义 |
| platform `RuntimeAuditPanel.tsx` | 原查询、独立状态提示与范围重置 | 不改历史账本、SDK、身份推断或共享 Select 视觉 |
| approval 服务与 Handler 工厂 | 原鉴权之后分派只读补充 | 不认识 F048 Grant 或修改审批决定/路由 |
| 拟新增 app_publish 当前摘要服务 | 核对 app/tenant/instance 绑定、协调 F048 来源与目录、输出小 DTO | 不写 snapshot、不授予权限、不直接查权限表 |
| permission.application 端口与 runtime/control_state | 现有 Catalog/投影/继承下的 action 来源与完整性 | 不依赖审批、用户或应用业务 ORM，不暴露新的 HTTP roster |
| tenant 主体目录及所属 Repository | 批量当前对象资格与名称 | 不展开所有成员、不替代 F048 动作判定 |
| knowledge Web 创建策略及原异步创建流程 | 当前身份/租户和创建资格、写前重验 | 不更改复制/开放通道资格、角色菜单或资源归属 |
| user.application.runtime_identity 与所属 Repository | 复用当前人员事实，新增批量读取和 Web 新建用途薄入口；兼容关闭多租户 | 不新增身份来源、不为负责人制造会话、不改变原运行/预览严格入口 |
| client 审批面板 / platform 异常详情 | 各自渲染当前范围与重查；其余字段仍冻结 | 不在两个 SPA 之间混用状态、API 包装或页面组件 |

三语键分别落各应用现有 locale；新增业务错误对应 `packages/locales/src/api_errors/{zh-Hans,en,ja}.json`。实施时同步 approval-module skill 的详情 API 和场景补充接线说明，不更改审批人解析规则。

### 4.8 本地实现补充（2026-11-02）

- `user.application.runtime_identity.read_current_person_facts` 及 `resolve_web_creation_identity` 已接线；新建用途区分所属租户变化，原 runtime/preview 身份入口未改。
- F048 `SqlPermissionControlState.source_read_stamp` 经仓储读取继承链的模式/Grant版本，`read_effective_action_sources` 完整分页后再次复核模式与Catalog。业务摘要在名称、负责人资格查完后再读一次来源，变化返回 unavailable。
- `AppPublishCurrentVisibilityService` 由原审批门禁后的 app Handler 调用，超时预算5秒；目标 app/tenant 校验先于删除态和目录读取。DTO 使用 `userset_relation`（含 subtree_member），两端按成员、管理员、含下级分别显示。
- 新建 endpoint 只使用验证过的真实所属租户，async create 在模型和重名检查后、首个写入前重验会话及资格；Web 专用 `expected_tenant_id` 不扩展共享 KnowledgeCreate。
- 管理异常页重复展开、显式刷新均重查，旧异步响应用序号丢弃；管理租户切换沿既有 `bisheng:management-scope-changed` 全页重载清空内存。客户端真实父层为 `ApprovalPane.tsx`，刷新仍调用原详情 API。
- 知识库表单缺少所属租户时阻止提交并提示刷新重开，不推测为1；服务端单租户 user/info 已有确认的1语义时才可发送1。新建与复制条件已分开。
- manager 状态采用显式 no_execution/execution_missing/current；已停止执行体不保留失败探活相位，归属变化或平台资源读取失败不伪装成执行体丢失。K8s专用只读observe_status仅将精确Pod 404识别为丢失；原observe生命周期入口不变，Service/Endpoint等依赖失败仍不可确认。
- 未新增表、权限动作或外部依赖。新增10993及三语产物已落地；E2E脚本仅显式开启后访问真实环境，创建另需写入开关，清理校验精确名称、人员和租户。

## 5. 已知坑与处理

| # | 事实 | 若忽略会怎样 | 处理处 |
| --- | --- | --- | --- |
| 1 | 有运行容器不等于配置了原生 Health；平台已有独立应用探活 | 继续显示空健康，或把 Running 冒充健康 | manager observe/status，D1 |
| 2 | K8s app 状态缺失时现有 sum 默认为 0 | 把未观测到数据当成真实零 | K8s `_observed` 与 nullable 映射 |
| 3 | 后端无实例回退会读旧 AppInstance | 旧时间和健康出现在已替换实例上 | `app_query_service.get_instance` |
| 4 | v1 字符串在只读客户端内被强制改成 v2 | 为修显示重新接通已退役控制协议 | `orchestrator_client._v2_request`，保持 v2 |
| 5 | 模型应用自身调用没有自然人 subject；候选目前已有真实数据 | 补 owner 会篡改审计含义 | 审计仓储保持；过滤器补空态 |
| 6 | 授权模型名称/level 不等于当前 action_codes | 误把只有 edit 的对象当访问者 | F048 action 来源端口 |
| 7 | 承载源的投影中间态、分页截断不能当完整空集合 | 错误宣称“仅负责人可见” | CURRENT/版本前后校验、有界失败显式 unavailable |
| 8 | 现有 canonical_source 对人只核成员行，display_names 只装饰名称 | 已停用或迁租户人员仍列为有效 | 主体目录新增批量资格解析，不直接复用为完整证明 |
| 9 | 草稿/下线不清空授权；负责人可能仍记在历史单但已失去资格 | 首发永远查不到范围，或无效负责人被认定可见 | app 业务目标与真实 owner use 分离 |
| 10 | 部门 subtree、用户组 admin 与整个对象成员含义不同 | 文案把仅部分 userset 授权夸大成全部成员 | DTO 保留 relation/include_children，前端标注 |
| 11 | 异常进度按 exception ID 缓存详情 | 授权变化后仍永久显示旧范围 | `useApprovalExceptions` 按 scope/instance 重查 |
| 12 | 新建条件同时控制复制，页面租户也不等于创建归属 | 一次补按钮造成复制扩权或写到所选租户 | Doc/QA 条件分离，表单 expected tenant + Web 策略 |
| 13 | 同步与异步知识库创建、开放通道共用底层创建逻辑 | 将 Web 菜单门禁加到 SDK 或重复创建流程 | 仅 Web 入口带上下文，复用 `acreate_knowledge` 与原底层 |
| 14 | 运行任务身份函数要求有效 UserTenant；旧单租户用户未必有该行 | 复用后把原来可创建的人全拒绝 | user 应用模块新增用途入口，关闭多租户时固定 1；原 runtime 严格合同不改 |
| 15 | `resolve_permission_actor` 优先返回当前请求 actor | 查负责人时错误使用阅读者的超管/普通身份 | 负责人按自身事实构造 actor，不能借请求缓存代验 |

## 6. 对外契约与依赖

### 6.1 提供与兼容

| 提供项 | 形式/消费者 | 兼容与限制 |
| --- | --- | --- |
| 当前运行事实 | 原 manager v2 status、平台 instance API | 字段增量；计数 nullable。manager/backend/frontend 一起升级后才算运行信息交付；旧字段缺失表达未知，不保留错误回退 |
| `current_visibility` | 原三个审批详情，client 面板和 platform 管理详情 | 同级增量；旧客户端可忽略，但不会获得本功能新显示；新客户端对旧后端显示未知，绝不把旧 snapshot 冒充当前 |
| `read_effective_action_sources` | permission.application 可信服务端协议 | 需要业务验证目标与既有前置阅读资格；仅摘要用途首个调用点，通用 roster 管理门禁不变 |
| `read_current_detail` | app 发布 Handler 可选补充 | 只读，非 app 场景没有补充方法时返回无增量；不改 resolver/outbox |
| `expected_tenant_id` | Web knowledge/create 请求增量 | 只作前置条件，不是跨租户创建能力；旧调用以已验证 JWT 租户作预期，不改变共享开放 API 请求 |
| 知识库 Web 创建策略 | 原 endpoint 与已有异步创建服务 | 不扩大复制与其它通道；前置失败无创建副作用，成功沿原投影/索引/审计 |

### 6.2 错误与展示状态

| 情形 | 合同 |
| --- | --- |
| manager/平台/集群不可用或执行归属不匹配 | 复用 `AppOrchestratorUnavailableError` 16121，保留安全 reason；不转换成无应用 |
| 原审批无阅读资格 | 原 `ApprovalRequestPermissionDeniedError` 18101；在任何摘要查询前拒绝 |
| 授权投影/目录失败或摘要超预算 | 当前区域 `state=unavailable` 与固定 reason；日志留异常，冻结详情保持；不新增独立错误码 |
| 应用已删除 | 当前区域 `state=deleted`，保留合法可读历史；不恢复应用 |
| 当前 Web 身份失效/无创建资格 | 沿原身份及权限错误；前端统一请求层处理 |
| 新建预期所属租户与实时身份不一致 | 拟新增 `KnowledgeCreationScopeChangedError` **10993**，文案明确所属租户已变化，请重新打开表单；本次基线全部错误码扫描未占用。仅此一条新业务码，实施前重扫；若已被其它变更占用，选未占用码并同步本文与三语，不能复用冲突码 |

10993 登记在 knowledge 现有模块及版本契约，不新占模块；`/api/v1` 沿原业务错误 envelope，不擅自修改全站 HTTP 状态。未新增密钥、凭据、敏感字段或真实账号密码。

### 6.3 依赖与风险

| 依赖 | 当前用途 | 变化风险 |
| --- | --- | --- |
| 当前应用绑定及 manager 执行器 | 当前事实与安全边界 | exec_ref/UID 失配或旧 manager 不能证明当前值，必须未知/错误，不能降级旧绑定 |
| Kubernetes Pod/Ready/EndpointSlice；Docker inspect 和已有 HTTP 探活 | 精确当前应用容器 | API 失败不得等同负探活；新的容器名或 readiness 口径需同步观察测试 |
| F048 CURRENT Catalog/Store/model/投影 | action 与完整来源 | pin 不一致、重发布/投影中必须不可确认；本功能不运行修复或迁移 |
| 主体目录、人员唯一当前成员与租户状态 | 名称、对象资格、创建身份 | 目录失败与已失效不同，不能用名称存在推断资格；业务层批量解析保持租户上下文；单租户关闭模式固定 1，不要求额外成员行 |
| 审批个人与管理阅读门禁 | 窄只读例外前置资格 | 不能将摘要服务直接暴露到只知道 ID 的请求，也不把 admin 进度资格变成同意权限 |
| 原知识库异步创建及投影补偿、embedding 回退 | 复用实际创建 | 不复制创建算法；新策略不得影响开放 API 默认模型或复制路径 |
| 共享 Select / 各应用现有 API、i18n、时间工具 | 文案与交互 | 不改共享组件视觉、不新增状态库；两个 SPA 不混用，三语同时交付 |
| MySQL/DM8、OpenFGA、Redis、现有索引服务 | 原平台依赖 | 无新增服务或本地权威存储，无 DDL；DM8 兼容由审查及中央环境回归验证，不伪称本机已实测 |

## 7. 定向验证与可观测

### 7.1 本地验证策略（实施后执行）

只覆盖本功能改变的行为和具体风险，不运行仓库全量测试。新增 backend 测试放所属 `test/<module>/`；没有业务代码的设计阶段不跑业务测试。

| 层 | 必要验证 |
| --- | --- |
| manager 单元/接口 | Docker 有/无 Health 的真实探活、启动/异常/未知、0/正数/null、未启动日期；K8s app/init 区分、Ready/Endpoint UID、缺 containerStatuses；停止/丢失/切换绑定与查询无写副作用 |
| backend 状态 | 只读字段和 nullable、依赖错误 vs 无绑定、拒绝旧 AppInstance 数据回退、原状态阅读权限不变 |
| 审计后端/前端 | 原真实身份/授权范围配对；app-self 与人混合时候选/筛选；空、搜索空、加载失败重试；切租户和过滤条件后的旧响应不污染 |
| permission/目录 | use 动作与 model 名称分离、直接与继承、projection/catalog 切换、分页完整性/预算、停用迁租户、对象失效/服务失败、userset 不展开、未知 tenant 来源不误报 owner-only |
| 审批服务与页面 | 先鉴权后补充；有任务无长期 manage_permission 可读摘要但通用 roster 拒绝；进行中/终态、个人/管理三入口，owner-only/多类对象/负责人失效/删除/故障；snapshot 深度相等、其它三个审批场景不增加摘要调用 |
| 知识库 | 无菜单租管 Doc/QA 成功；普通无菜单拒绝/有菜单成功；部门管理不新增资格；新建与复制分离；迁租户/停用/撤资格/会话变化前置拒绝；关闭多租户且无成员行仍保持原创建资格；原 embedding/索引与创建者投影不绕过 |
| 三语与静态 | 变更文件 lint/typecheck/相关组件测试、三语键及错误码冲突检查；不因修文案引入全量回归 |

后续测试命令以明确文件选择执行，例如：

```sh
# 在 src/backend 中，仅指定本功能新增/受影响用例；不传整个 test/。
uv run pytest test/app_runtime/test_app_query_service_entry.py test/app_governance/test_runtime_audit_query.py
# 新增的摘要、Web 创建资格用例在任务阶段列出精确文件名。
# manager 在 src/runtime-manager 中选择 v2 状态与 K8s 观察用例，不跑已退役 v1 测试作交付证明。
python -m pytest tests/test_operations_v2.py tests/test_k8s_observe.py
```

这些是待实施验证入口，不是本轮已运行的记录；最终命令、环境、数量和失败基线记 verification。

### 7.2 必需真实 E2E 与操作步骤

真实验收仍是 SDD 必需步骤，但本轮只确认设计，不自动授权环境服务更新或业务写入；镜像、质量门禁及账号准备后按用户另行授权执行一次本功能定向验收。

1. 核对 116 的 backend/worker/platform/client 与 runtime-manager 实际镜像和本次提交；由用户授权更新相关服务后再测，不将旧 F114 manager 当作新状态合同的证明。
2. 使用专用 `e2e-f115` 人员、租户、应用与可清理知识库，不修改 gzx01 或三个存量应用归属；凭据经安全环境注入，会话仅进程内。
3. 在 `[116:3001]/build/apps/{test_app}` 核对健康、重启次数、浏览器本地启动时间与精确容器事实一致；用专用应用验证停止/无执行体；K8s 用具备同版本部署的专用环境验证，未授权或未部署则标未验，不冒充 116 已验证双形态。
4. 在 `/log` 的模型调用查询中，用真实 OBO 自然人调用与应用自身调用配对；检查候选、过滤与切范围，用无记录范围验证提示，不修补现有示例应用或历史日志。
5. 在 `/workspace/settings/my-tasks`、`my-requests` 及 `/approval` 的测试审批详情，依次读取仅负责人、增人员/部门/组、撤销/失效；刷新后变化但版本/说明/声明/决策快照不变。用有阅读资格但无 app.manage_permission 的人员做正向摘要和反向通用 roster 验证。
6. 本租管无创建菜单时在 `/filelib` 新建文档和 QA 库；源读取和创建菜单不足时复制仍拒绝。专用人员表单打开后迁租户或撤资格，提交不产生旧/新租户资源；普通有/无菜单及超管归属规则配对。
7. 清理仅本轮已创建的测试对象，并记录未清理原因；不停止、迁移、重建无关实例。审批引擎其它场景仅做本次补充钩子“不调用”合同验证，不改通用 resolver，因此不跑无关全场景业务回归。

### 7.3 日志与发布核对

- manager 记录 app/exec_ref/operation/node/UID、观察分类及安全失败原因，不记录应用环境变量值。
- app 发布摘要日志记录 instance/app/tenant、检查结果/耗时、来源数与安全 reason；失败带异常，不输出完整授权目录到日志。不得把当前摘要日志作为历史授权变更审计的替代品。
- 知识库拒绝记录人员/预期租户/经验证所属租户及失败类型；成功继续现有创建审计，不记录会话引用的 token 或密钥。
- 发布次序：先上能识别“新字段缺失=未知”的兼容 platform/client，再上 manager 与 backend；避免新 backend 的 null 计数被旧 UI 的 `??0` 显示成零。知识库 UI 与 Web create 增量配套，全部镜像到位才进行交付验收。无 DDL、无数据迁移；回滚代码不会重写数据，但旧 UI 不提供本次新展示，旧后端不会识别新资格。部署和回滚均须明确服务范围。

### 7.4 AC 追溯

| 规格范围 | 设计落点 |
| --- | --- |
| AC-01–AC-10 | D1、§4.2、§4.5 实例状态、§7.1 manager/backend |
| AC-11–AC-21 | D2、§4.3、§7.1 审计 |
| AC-22–AC-27 | D3/D4、§4.4 A–C、§4.5 当前摘要 |
| AC-28–AC-31 | §4.4 C–D、§4.5 available/不可确认区分与冻结保持 |
| AC-32–AC-38 | §4.4 A/D、§6.1、§7.1 三入口和反向权限验证 |
| AC-39–AC-44 | D5/D6、§4.6、§6.2、§7.1 写前资格 |
| AC-45–AC-50 | D5、§4.6 原菜单/复制/通道/模型保持 |
| AC-51、AC-52 | §2、§4.7、§6、§7.1–§7.3 |

## 8. 不投入项与重审条件

- 长期监控、重启历史趋势、统一探活门槛：本轮只补当前事实；后续有明确运维需求再立项。
- 用户姓名审计快照和历史访问者回填：现有日志没有事实就不造数据；新身份采集由独立 SDK/OBO 需求推进。
- 超大授权范围的完整分页审批浏览：本次超过预算表达不可确认，不增加新通用目录 UI；真实遇到大规模场景再审只读分页与身份一致性。
- 资源迁移/移交、管理员代创建到任意租户、知识库复制扩权：均未授权，不作为创建异常的兜底。
- 通用审批 resolver、路由、outbox 与其它场景的当前授权展示：不在本次改动；若未来修改，需要按审批 skill 重新界定跨场景验证。

## 修订历史

| 日期 | 改动 | 触发原因 |
| --- | --- | --- |
| 2026-11-02 | 初版设计，52 条 AC 追溯；区分既有现状与拟实施方案 | 用户确认正式规格并要求进入设计；设计尚待单独确认 |

| 2026-11-02 | 用户确认后按44个原子任务落地；补源版本双读、userset_relation、真实父层、Nullable运行事实与创建前重验；本地门禁和真实E2E分开记录 | 代码接线核对与定向验证；未改已确认AC或授权环境更新 |

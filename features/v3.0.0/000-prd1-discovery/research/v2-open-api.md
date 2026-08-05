# v2-open-api

## summary
v2 开放 API（/api/v2/**，实现在 src/backend/bisheng/open_endpoints/，8 个路由文件约 50+ 端点）现状为零鉴权：全部端点以 DB 配置的 default_operator 固定用户身份执行，4 处接受裸 user_id 代用户（resolve_operator 只查用户存在）。伴生 PRD《3.0 开放 API 鉴权与身份传递》v2.0 已定稿 R1-R9 需求（bs-sak-/bs-pat- 双轨凭据、SHA-256 哈希存储、三身份模式、受限委托六道准入、撤销≤5s），与 PRD-1 GOV-08 的三类 key 体系（个人 key=bs-pat- / 应用 token=bs-sak- 服务账号密钥 / 会话 key）互链对齐。代码核实：凭据层为纯新建（全仓无任何 ApiKey 表/bs- 前缀/require_api_key 配置），但随机源、恒时比较 HMAC 校验、bypass_tenant_filter 查 token 先例、租户 ContextVar 机制均有现成件可复用；鉴权挂点在 api/router.py:94 的 router_rpc 及各端点内联的 get_default_operator 调用（多数非 Depends 形态，需逐端点改造）。

## current_state
【伴生 PRD 消化（已全文通读 1014 行）】需求编号实为 R1-R9：R1 凭据体系（P0 服务账号密钥 bs-sak- / P1 个人访问令牌 bs-pat-；SHA-256 单向哈希+唯一索引、不加盐、不用 Fernet 可逆加密（其密钥硬编码在 core/config/settings.py:20 随开源分发）；明文仅创建时一次展示，列表只显前缀+末四位；有效性=「撤销时间为空且未过期」单一判据、不设 status 枚举列；校验六步流程=提取 Bearer → bypass_tenant_filter 下按 sha256 查行 → fail-closed 恒时比较/未撤销/未过期/主体有效/主体租户==密钥租户 → set_current_tenant_id → 构造 UserPayload → Redis 缓存 TTL 5s+撤销主动删缓存即「撤销≤5s」）；R2 三种互斥身份模式（S 默认服务账号 / D 委托头 X-Bisheng-On-Behalf-Of / E 外部标识头 X-Bisheng-End-User 纯标签不参与鉴权）；R3 三条铁律（无凭据 401、缺身份≠放行全部、权限引擎失败 5xx fail-closed）+ 受限委托六道准入（delegate 权限位/委托模式非 none/目标存在未禁用同租户/目标非超管非租户管理员=防提权核心/scoped 类型化范围/端点白名单），D2 已定为纯替换非取交集（ListObjects 被 DenyListObjectsPolicy 禁用、无缓存、创建类无前置检查、交集致委托头静默失效四条理由）；R4 服务账号=复用 User 表新增 user_type 列+source=service_account+external_id=NULL 结构性免登录+租户关联声明式直写+三层对账豁免+/user/list DAO 层默认排除；R5 端点接入含两个 WS 握手鉴权（走 Authorization 头，明确不用查询参数——t 参数路径是坏的）+补工作流上线状态/停止会话归属校验；R6 管理界面；R7 审计双归属 actor+subject；R8 限流配额幂等 P2（平台无任何 HTTP 限流基建）；R9 存量迁移（open_api.require_api_key 开关默认 false 兼容窗口、default_operator 转型为默认服务账号并强制降权）。附录 B 关键事实澄清＝旧检索路径不可原样沿用：/api/v2/filelib/retrieve 走的 knowledge_space_chat_service.py:812-872 只做知识库级一次校验、无文件级过滤；工作台文件夹对话路径（同文件:484-570）才有索引层预过滤+结果层兜底两层；且权限模型中不存在 view_file/view_space 关系、实际统一用 visible——PRD-1 v1.5 的「声明白名单∩用户文件级权限+fail-closed」检索语义必须基于两层过滤路径而非旧 retrieve 路径。附录 E 措辞红线：受限委托是「提权有上界」非「恒为降权」、模式 E 不等于不做权限过滤。
【代码现状（均已在本 worktree 核实）】路由拓扑：bisheng/api/router.py:94 `router_rpc = APIRouter(prefix='/api/v2')` 聚合 8 个子路由（:95-102），bisheng/main.py:144 `app.include_router(router_rpc)` 挂载；子路由文件在 open_endpoints/api/endpoints/{workflow,assistant,chat,filelib,knowledge,flow,citation,llm}.py，经 open_endpoints/api/router.py 汇出。端点面：workflow（POST /invoke :31 无上线状态校验、POST /stop :144 无会话归属校验、WS /chat/{workflow_id} :157 中 jwt_required 被注释 :165-166 且 docstring 明写 Use Exempt Login Link）；assistant（POST /chat/completions :33、GET /info/{id} :259 与 GET /list :274 有 enable_guest_access 配置门但身份仍是 default_operator、/list 收裸 user_id 参数但当前只写日志不参与身份、WS /chat/{assistant_id} :294 无鉴权且 get_default_operator() 在 :300 位于 try 块外配置缺失会裸崩）；chat（6 端点，POST /sync/messages :80 直接把请求体裸 user_id 写入 ChatMessage、连用户存在都不查、缺省回落 default_operator 配置值）；filelib（20 端点含匿名建/改/删知识库与上传，GET / :173、GET /file/list :378、POST /retrieve :637 三处经 resolve_operator(user_id) 代用户）；knowledge（8 个 metadata 端点，走 Depends(get_default_operator_async)）；flows GET /{flow_id}、citation GET /{citation_id}、llm POST /workbench/asr、/tts。身份解析：open_endpoints/domain/utils.py——get_default_operator(:26)/get_default_operator_async(:53) 从 DB 配置 default_operator.user 取固定用户构造 UserPayload；resolve_operator(:77) 传了 user_id 就 UserDao.aget_user 查到即用（不查禁用、不查任何凭据），F030 上线的活越权通道。调用形态分两种：knowledge.py/citation.py/dependencies.py 走 FastAPI Depends(get_default_operator_async)；其余大多数端点在函数体内联调用 get_default_operator*/resolve_operator（非 Depends）——鉴权改造不能只在 router 层加 dependencies，必须逐端点替换身份来源。
【租户处理】HTTP 中间件（utils/http_middleware.py:105-118）只从 JWT cookie 设租户 ContextVar，v2 调用无 cookie 故 ContextVar 为空；三个操作员解析函数在末尾 set_current_tenant_id(解析出用户的活跃 UserTenant 租户)（domain/utils.py:49/:73/:103）补种上下文，此后 tenant_filter 的 do_orm_execute 监听自动注入 WHERE tenant_id（仅拦 SELECT，core/database/tenant_filter.py）。注意 resolve_operator 的租户来自目标用户＝调用方可控。WS 中间件已读 scope['headers']（http_middleware.py:395-412），服务端到服务端可传自定义头；而 AuthJwt.get_subject（user/domain/services/auth.py:196-211）在 auth_from='websocket' 且 websocket 非空时无条件用 cookie 覆盖传入 token——get_login_user_from_ws(:651) 的 t 查询参数是死的，WS 鉴权 100% 依赖 cookie，PRD「不采用查询参数」结论与代码一致。
【既有 api-key 类机制】grep 全仓证实无任何 API key 表/模型/bs- 前缀/require_api_key 配置。最接近的四件均不可复用（与 PRD §4.2.1 逐条一致）：share_link token 明文存储且 expire_time 注释明写 intentionally not enforced（share_link_service.py:52-58）；gpts_tools.api_key（tool/domain/models/gpts_tools.py:61）是用户手填的第三方密钥非平台签发；invite_code 非密码学随机；sso_sync 网关 HMAC 是共享密钥签名不签发凭据。User 模型（user/domain/models/user.py:71）无 user_type 字段，服务账号主体需 Alembic 变更。

## key_files
- docs/product/3.0 开放 API 鉴权与身份传递 PRD.md — 伴生 PRD v2.0 全文 1014 行已通读；R1-R9、六步校验流程、六道准入、附录 B 端点改造清单与旧检索路径事实澄清、附录 C 错误码 26001-26012
- src/backend/bisheng/api/router.py — :94-102 router_rpc = APIRouter(prefix='/api/v2') 聚合 8 子路由——HTTP 层鉴权依赖的天然挂点（router 级 dependencies）
- src/backend/bisheng/main.py — :144 app.include_router(router_rpc) 挂载 v2
- src/backend/bisheng/open_endpoints/domain/utils.py — get_default_operator(:26)/get_default_operator_async(:53)/resolve_operator(:77) 三个身份解析函数＝改造的核心替换点；均在末尾 set_current_tenant_id 补种租户上下文
- src/backend/bisheng/open_endpoints/api/endpoints/workflow.py — invoke :31 无上线校验、stop :144 无归属校验、WS :157 鉴权被注释(:165-166)
- src/backend/bisheng/open_endpoints/api/endpoints/assistant.py — WS :294 无鉴权且 get_default_operator 在 try 外(:300)；/list :274 收裸 user_id 仅记日志；info/list 有 enable_guest_access 门
- src/backend/bisheng/open_endpoints/api/endpoints/filelib.py — 20 端点；resolve_operator 代用户三处 :173/:378/:637；匿名建改删知识库与上传
- src/backend/bisheng/open_endpoints/api/endpoints/chat.py — sync/messages :80 裸 user_id 直写 ChatMessage 不经任何解析校验
- src/backend/bisheng/open_endpoints/api/dependencies.py — 既有 Depends 链先例：get_knowledge_space_chat_service_for_openapi 经 Depends(get_default_operator_async) 注入身份——新鉴权依赖的替换样板
- src/backend/bisheng/core/context/tenant.py — 租户 ContextVar：set_current_tenant_id/bypass_tenant_filter/strict_tenant_filter；密钥校验第 2 步与第 4 步的直接依赖
- src/backend/bisheng/core/database/tenant_filter.py — :39-102 _TENANT_AWARE_MODEL_MODULES 手工注册清单——新密钥表必须注册，:36-38 注释记录 v2.5 漏注册事故；自动过滤只拦 SELECT
- src/backend/bisheng/utils/http_middleware.py — :105-118 HTTP 中间件仅从 JWT cookie 设租户；:395-412 WS 中间件读 scope headers（WS 握手传 Authorization 头可行的代码依据）
- src/backend/bisheng/user/domain/services/auth.py — AuthJwt.get_subject :196-211——websocket 分支无条件用 cookie 覆盖传入 token，t 查询参数是死路径；UserPayload.get_login_user :625 为 v1 鉴权依赖形态参照
- src/backend/bisheng/sso_sync/domain/services/hmac_auth.py — :44-109 verify_hmac——全仓唯一恒时比较+fail-closed 的 FastAPI 鉴权依赖实现，姿势应被新密钥校验抄用（含 body 重放技巧）
- src/backend/bisheng/common/utils/util.py — :28-55 generate_short_high_entropy_string——全仓唯一合格随机源，密钥生成复用
- src/backend/bisheng/share_link/domain/services/share_link_service.py — :32-60 bypass_tenant_filter 下按 token 查行的同构先例（注释语义＝token 本身就是授权）；同时是明文存储/过期不校验的反面教材
- src/backend/bisheng/user/domain/models/user.py — :71 class User——无 user_type 字段，服务账号主体需 Alembic 变更；_filter_users_statement 为 /user/list 分叉的下沉点（PRD 引用，函数存在性已核）
- docs/product/3.0 应用工场 PRD-1 专业开发者通道与应用运行时.md — :747-787 GOV-08 三类 key 总纲：应用 token=bs-sak- 服务账号密钥、存量迁移用 SAK 非个人 key、兼容窗口为部署配置项、掩码=前缀+末四位

## reuse
- 密钥生成随机源：common/utils/util.py:28-55 generate_short_high_entropy_string（os.urandom+HMAC-SHA256+urlsafe base64），PRD 点名全仓唯一合格随机源，直接复用
- 校验姿势：sso_sync/domain/services/hmac_auth.py:44-109 verify_hmac——hmac.compare_digest 恒时比较、secret 未配置即拒绝的 fail-closed、作为 FastAPI 依赖（async def verify_x(request: Request)）的完整形态，新密钥校验依赖照此抄写
- 跨租户查凭据先例：share_link_service.py:32-60 在 bypass_tenant_filter() 下按 token 查行并附注释论证「token 本身就是授权」——密钥校验第 2 步同构复用该模式
- 租户上下文机制：core/context/tenant.py 的 set_current_tenant_id / bypass_tenant_filter 全套现成；密钥校验通过后 set_current_tenant_id(密钥租户) 即接入既有自动过滤（PRD 六步流程第 4 步）
- 身份对象构造：UserPayload.init_login_user（get_default_operator_async :66-74 已示范 user_id+user_name+tenant_id → UserPayload），密钥解析出主体后复用同一构造，下游服务（KnowledgeSpaceChatService 等）零改动
- Depends 注入样板：open_endpoints/api/dependencies.py:61-77 与 knowledge.py/citation.py 已用 Depends(get_default_operator_async)——新 auth 依赖可原位替换这些 Depends；router_rpc（api/router.py:94）可加 router 级 dependencies 兜底强制
- 服务账号主体：D4 已定复用 User 表（新增 user_type 列），权限授予/OpenFGA 投影/资源归属链路全部沿用现有用户主体机制，不建平行主体体系
- 委托 scoped 范围的部门子树判定：复用 database/models/department.py 的 UserDepartment+Department.path 物化路径单次索引查询（PRD 引用，本次未逐行核）
- WS 握手读头能力：utils/http_middleware.py:395-412 已在读 scope['headers']，服务端集成经 Authorization 头传密钥无需新中间件能力
- 新密钥表建表走既有 SQLModel create_all(checkfirst) 机制（backend AGENTS.md 规约），仅 user_type 等存量表改列需 Alembic revision

## gaps
- 凭据层纯新建（grep 全仓证实零基础）：密钥表（tenant_id/主体类型+ID/名称/前缀+末四位/SHA-256 哈希唯一索引/权限位/资源白名单/委托模式+范围/过期/最后使用节流/软撤销时间）+ 生成/签发/校验/撤销服务 + Redis 5s 缓存与撤销主动失效
- 开放 API 鉴权依赖：新 FastAPI Depends（HTTP）+ WS 握手校验（Authorization 头），替换 8 个路由文件里全部 get_default_operator*/resolve_operator 调用点——多数为函数体内联调用而非 Depends，需逐端点改造（附录 B 清单约 50+ 端点）
- 三种身份模式解析器（S/D/E 互斥判定、双头冲突 400）+ 受限委托六道准入检查（含特权主体禁令 26007、类型化委托范围匹配）
- 服务账号主体全链路：User.user_type 列（Alembic）+ source=service_account 枚举 + 密码哨兵 + 登录守卫（公共守卫 1 处+单独 3 处）+ 租户关联声明式直写与对账豁免（worker/tenant_reconcile/tasks.py 加 human 过滤）+ /user/list DAO 层分叉 + 配额统计排除
- 管理面：密钥管理页（创建一次性展示/列表掩码/编辑不轮换/撤销与批量撤销）+ 服务账号管理新端点 + PRD-1 GOV-08 的三 tab 结构（个人 key/应用 token/服务账号）+ 兼容窗口状态展示
- 存量迁移件：open_api.require_api_key 配置开关 + 无密钥回落时的 WARN/迁移告警 + default_operator 转型脚本（scripts/，非 DB 迁移）+ 文档修订（删除「建议配超管」表述）
- 错误码模块 260 新增（26001-26012）注册进 common/errcode/
- 开放 API 审计（R7 双归属 actor+subject）——现有 audit_log 无此语义，需新记录面
- 补漏的业务校验：workflow invoke 上线状态校验、stop 会话归属校验、assistant WS 身份解析移入 try 块
- WS 鉴权若要支持浏览器直连需子协议或票据换取机制（服务端集成走头可先行）；t 查询参数路径已证实是死代码，不修不用
- P2 项全部无基建：HTTP 限流（无 slowapi 类依赖）、幂等键、IP 白名单

## risks
- C3 租户隔离：新密钥表若漏注册 _TENANT_AWARE_MODEL_MODULES（tenant_filter.py:39-102）会静默把子租户密钥写进根租户——:36-38 注释记录的 v2.5 事故同型；且自动过滤只拦 SELECT，密钥表批量 update/delete 必须手写租户条件（PRD 已明令禁止批量写）
- 现行 resolve_operator 的租户上下文由调用方指定的目标用户派生（domain/utils.py:96-103）＝攻击者可控租户种子；改造期兼容窗口内该路径仍活着，窗口策略（R9）必须显式覆盖此点
- 逐端点改造的遗漏面大：身份解析是内联调用非统一 Depends，漏改一个端点即残留匿名通道；建议配 router 级强制依赖+全端点测试矩阵兜底（PRD AC-1/AC-14 的测试矩阵思路）
- 检索路径事实（C4 相关）：/api/v2/filelib/retrieve 现走的 knowledge_space_chat_service.py:812-872 只有知识库级校验、无文件级过滤；PRD-1 v1.5 已定「声明白名单∩用户文件级权限+fail-closed」——若沿用旧路径将直接违约，需切到两层过滤路径（同文件:484-570）并专项验证无「过滤器异常被吞→返回全量」路径（铁律 F3）
- 不得回退到「权限取交集」：ListObjects 被 DenyListObjectsPolicy 禁用（sql_runtime.py 装配）、主链路无缓存——D2 已改判受限委托，设计评审时勿再提回（memory 明确标注）
- 委托模式的提权语义：受限委托=「提权有上界」非「恒为降权」，服务账号窄权限+delegate 可获得目标用户的更宽权限；特权主体禁令（检查 4）是唯一防无界提权的闸，实现与测试（AC-7）必须优先
- chat.py sync_message 裸 user_id 直写消息（连 resolve_operator 都不走、不查用户存在）——比 PRD 引述的 F4 更松，收口清单须包含它
- 兼容窗口默认 require_api_key=false 期间 AC-1 不成立，安全敞口持续存在；窗口长度（D1）未决且 PRD-1 说是部署配置项，需在发布说明显式披露
- 错误码 260 段占用未确认（D5），与 constitution C5 的 MMMEE 分配需先对账
- Fernet 不可用于密钥存储（其 key 硬编码 settings.py:20 随开源分发）——任何「加密存储便于找回」的提议都应按 PRD §4.2.5 驳回，存哈希是唯一口径

## open_questions
- D1 兼容窗口长度：PRD 建议一个大版本，PRD-1 GOV-08 定为部署配置项——默认值取多少、窗口结束是否需要显式运维动作确认
- D5 错误码模块号 260 是否与既有规划冲突（需产品/架构确认分配表）
- D6 已部署商业版网关的客户是否由网关充当令牌签发方（一期不做，但请求头抽象要不要预留网关透传约定）
- D7 服务账号是否允许更换租户（建议禁止、禁用后新建），涉及名下资源归属与密钥缓存失效
- PRD-1 §6：个人 key（DEV-01）与伴生 PRD 的个人访问令牌（P1）是否合并为同一凭据实例（一把 key 同时通行 MCP/模型/CLI 与开放 API）——随 P1 落地定夺
- assistant info/list 现有 enable_guest_access 配置门在新体系下的去留（保留为额外开关还是随 R9 移除）
- WS 浏览器直连场景本期是否交付（子协议 vs 票据换取），或一期仅支持服务端集成走 Authorization 头
- 委托范围（scoped）管理界面的粒度与交互：users/departments/user_groups/roles/tenant_wide 五型全部一期做，还是先做 users+departments

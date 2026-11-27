# Token Exchange 技术设计

状态：用户已明确“设计确认，开始编码”，进入实现与验证。关联：[已确认规格](./spec.md)、[进度](./tasks.md)。目标发版线：feat/3.1.0-alpha1；现状源码基线：572d5ecf77。以下新增能力已在本分支实现并完成本地验证，尚未部署。

## 1. 目标与约束

同一用户、同一租户从 A 换取 B 接受的短期登录Token。复用 F026，不改 B 产品自身代码，不支持代其他用户/租户登录、公开客户端直接交换、连锁交换或刷新交换凭证。遵循 docs/constitution.md C1–C8；发布契约按已确认规格登记OAuth身份断言与ApiCredential窄边界。

核心链路：A可信后端 → 原 /api/v1/oauth2/token 的新grant → 校验A、原凭证、A→B授权及身份 → 创建B独立会话和父会话关联 → ES256签发 aud=B → B校验并建立自身会话。

权限边界说明（回应用户对“如何保证不扩权”的问题）：这里的范围是OAuth身份scope，毕昇在服务端要求requested_scope全部属于“原Token ∩ 原会话 ∩ 当前A允许范围 ∩ A→B策略 ∩ 当前B允许范围 ∩ {openid,profile,email}”；任一超出整体invalid_scope，不静默裁剪。B自己维护的角色、资源和业务动作不在这份scope交集中，也不会自动继承或被裁剪成A的业务权限；交换Token不携带A管理员/角色标记。B以已验签的(iss,sub,tenant_id)绑定本地账号后按自己的权限模型授权。如要比较A/B业务权限，需另定义共同权限语义或映射，本轮不隐含承诺。此说明不改变已接受规格AC-06与范围，仅澄清其含义。

## 2. 三个实现决策

1. **复用标准Token接口和ES256/JWKS**，增加RFC8693 grant，而非另造登录接口或复用DSH模型令牌。现有keys服务已管理相同签名材料；输入只接受A所属毕昇OAuth Access Token。若未来需要外部IdP/B自签Token，重新设计信任链。
2. **新增两张独立表，复用现有B会话**，不在现有三表加字段。oauth2_exchange_policy保存平台级A→B白名单、scope、enabled及管理者/时间；oauth2_exchange_session保存B session_id到原A source_session_id的不可变关联及身份/来源/签发issuer。共享A会话会使B撤销影响A，因此不选；新增完整Token存储体系没有必要。若后续需要多级委托，再评审图和撤销策略。
3. **在线查父链，本地按期限退出**。每次新交换读取数据库当前状态，不缓存授权；UserInfo对交换Token额外检查父会话。无需在父撤销时批量更新子行，避免扩大既有撤销事务。若业务要求B离线验证也在5秒内撤销，必须改为B在线验证，不能仅靠JWT。300秒只约束交换Token，不会自动注销B已经建立的本地会话；B自己的会话寿命/登出由B集成方负责。

## 3. 现状与改动位置

| 现状入口 | 已核对的事实 | 本轮改动 |
| --- | --- | --- |
| api/endpoints/oidc.py::token | 仅处理authorization_code/refresh_token，复用Basic或表单认证；issuer优先部署public URL | 增加exchange分支及严格的单值参数校验，原分支不变 |
| domain/services/auth_service.py | decode_access_token目前关闭aud校验；UserInfo只查自身会话 | 不把这个宽校验器直接用于换证；仅对带交换标记的Token接入父链校验 |
| domain/repositories/session.py | 创建独立会话、刷新CAS、单会话和按client撤销 | 复用无refresh的B会话；不改变既有刷新锁顺序 |
| runtime.py | 注入DB session factory、keys、clients和实时identity_lookup | 注入独立ExchangeService及交换会话验证回调，避免Auth↔Exchange循环依赖 |
| api/protocol.py / common/errcode/oauth2_provider.py | public路由映射OAuth错误和no-store；28101–28114已使用 | 为新错误登记未占用281xx代码；管理接口保留平台envelope |
| domain/services/client_service.py | grant允许集合仅两个，默认值保持code+refresh | 允许显式登记exchange grant；不自动给存量客户端启用 |

API层只解析请求/准入；ExchangeService编排业务；ExchangeRepository及既有Client/Session Repository负责SQL。身份事实通过现有identity_lookup取得，不在新服务直接读用户/租户ORM。

## 4. 对外接口

### 4.1 换证

POST /api/v1/oauth2/token，application/x-www-form-urlencoded。A使用HTTP Basic携带client_id/client_secret；可兼容client_secret_post，但不允许与Basic矛盾或重复提供。

| 字段 | 约束 |
| --- | --- |
| grant_type | urn:ietf:params:oauth:grant-type:token-exchange |
| subject_token | A所属毕昇OAuth Access Token；不允许在URL中传Token |
| subject_token_type | 必须为 urn:ietf:params:oauth:token-type:access_token |
| audience | 唯一B client_id，必须不同于A |
| scope | 非空，显式空格分隔；只能取openid/profile/email |
| requested_token_type | 可省略或同access_token类型；其他类型拒绝 |

新换证请求body上限64KiB，subject_token上限16KiB，audience/client_id上限128字符、scope上限512字符，超限返回invalid_request；不把这些限制强加到旧grant。拒绝重复参数（含JSON原始重复键）、多目标、resource、actor_token/actor_token_type以及其他未支持的换证参数；不静默忽略身份/租户覆盖字段。JSON兼容输入遵守同样字段集合和标量约束；新的换证解析不得改变旧grant输入兼容性。

成功响应：access_token、issued_token_type（access_token URN）、token_type=Bearer、expires_in、scope、session_id（B会话ID）。没有refresh_token、refresh_expires_in或id_token。Discovery新增该grant；原client默认grant不变，A需通过现有客户端管理API显式加入该grant并配置允许的A→B策略。

JWT复用既有kid与ES256，包含iss、sub、tenant_id、aud=B、session_id=B、scope、token_use=access、iat、exp、jti，额外token_exchange=true、client_id=A。不把A的角色或业务权限复制进去；B用(iss,sub,tenant_id)识别身份，姓名/邮箱可通过受scope限制的UserInfo取得。

### 4.2 授权管理

平台全局管理员：GET /api/v1/oauth2/exchange-policies（page/page_size及可选source_client_id过滤）；PUT /api/v1/oauth2/exchange-policies/{source_client_id}/{target_client_id}（幂等创建/更新，body为allowed_scopes和enabled）。停用用enabled=false，保留记录；本轮不提供删除和UI。

创建启用关系前检查A为启用confidential且已允许exchange grant，B存在且启用，A≠B，scope非空且属于双方允许的身份scope。停用已有关系不要求被停用/删除的旧客户端再次启用。不存在关系时enabled=false仍按创建规则检查引用，不生成孤立策略。数据库复合主键保证同一A/B唯一；并发创建冲突返回28118管理业务错误，更新采用提交顺序生效；管理端沿用既有HTTP200+业务码envelope，不把它误报为HTTP409。

管理路由走现有PLATFORM准入，仅接受LoginUser已解析的is_global_super（或permission.application身份适配器的super_admin），拒绝tenant admin。现有is_admin()还兼容历史AdminRole，不复制其模糊语义，也不把旧入口误报为已证实的租户越权漏洞。返回使用UnifiedResponseModel/PageData。策略是平台应用信任关系；不能指定用户或租户。

### 4.3 错误和审计

invalid_client=401（A认证失败/公开客户端）；unauthorized_client=400（A未允许此grant）；invalid_grant=400（原凭证/父会话/身份不成立）；invalid_target=400（B或关系不可用）；invalid_scope=400；invalid_request=400（参数/类型不支持）。依赖状态不可确认则通用503 temporarily_unavailable，不降级签发。所有public响应含Cache-Control:no-store和Pragma:no-cache。预留新码28115=invalid_target、28116=unauthorized_client、28117=temporarily_unavailable、28118=管理策略冲突（当前errcode目录检查未占用），不改变旧错误码。新增业务错误文案同步locales源的en/zh-Hans/ja，再用现有生成器生成两前端产物，不手改生成文件。

每次结果记录服务端event_id、时间、结果/原因枚举、已认证A和已解析B、已验证user/tenant；未知身份记null，不记录攻击者伪造的用户信息。成功事件在事务提交后发出；策略变更记录管理员及结果。日志不包含请求体、Authorization、原/新Token、密钥，异常诊断保留类型和不含frame locals的堆栈；失败注入测试检查敏感值不泄漏。

## 5. 校验和会话流程

1. 开始校验即取UTC秒t0；验证参数、A客户端认证及grant许可。Basic与表单若重复提供身份或认证方式则拒绝，不使用“优先某一份”的歧义行为。
2. 用当前ES256公钥严格验证原Token的算法、签名、iss=本部署issuer、aud严格单值A；必要claims含exp/iat/jti/sub/tenant_id/session_id/scope/token_use，token_use必须access，正整数身份与会话事实一致。拒绝交换标记或已有交换关联的输入，禁止连锁。
3. 通过identity_lookup读取自然人、活动租户及有效成员关系。scope必须同时包含在原Token、原会话、当前A、当前B、当前A→B策略的允许集合，并限定三个身份scope；任何一项不满足整体拒绝。
4. 在短事务中用新session重新读取A/B、关系和原会话，重核对它们的存在/启用、身份及范围（不复用过期ORM快照）。原会话必须ACTIVE且未过期。身份查询后的并发失效按已确认的在途上界处理。
5. 取exp=min(原Token.exp, 原session到期秒, t0+B.access_token_ttl, t0+300)，到期不足一秒则拒绝。创建无refresh的B会话并在同一事务保存关联；时间均为UTC，DB秒值向下取整，不能因签名/排队重新起算寿命。签名后再次检查期限，超过则回滚；提交失败不得向调用者交付Token。
6. 返回前expires_in=max(0, exp-当前秒)，如已到期则拒绝。响应、日志均不延长exp。parent/child与policy跨服务重读可能发生在途变更，但t0锚定确保这类Token不会比变更提交后300秒更晚到期。
7. UserInfo看到token_exchange=true时要求关联存在，claims与B会话匹配；父A会话/父client有效、身份/租户一致、B会话/client有效、当前策略仍启用，且授予的全部scope仍包含在当前父会话、A、B及策略范围内；验证JWT issuer与关联所存issuer相同、aud=B、sub/tenant/session与child一致、exp不超过记录截止。父或策略失效返回invalid_token。普通Token仍走原路径；新校验回调未注入时不得放行交换Token。父/子client不存在或禁用统一转invalid_token，不泄露管理错误。单纯禁用后再启用client/policy，如果父子会话仍ACTIVE、当前全部范围仍允许且未过期，可恢复在线有效性；撤销或删除过的父子会话不得复活。
8. /revoke保持owner客户端认证：B只能撤销B会话，不能改A；撤销A后父链在线检查即时拒绝B，无须改动原Refresh CAS或反向撤销A。

## 6. 数据和升级

新增SQLModel均放oauth2_provider/domain/models，按现有自动发现机制注册；不改现有三表，不新增依赖。

| 表 | 主要字段与约束 |
| --- | --- |
| oauth2_exchange_policy | 复合主键(source_client_id,target_client_id)，allowed_scopes采用共享JsonType，enabled，created_by/updated_by，create_time/update_time采用共享server default |
| oauth2_exchange_session | session_id（B，主键），source_session_id（索引）、source_client_id、target_client_id、tenant_id/user_id、issuer、created_at/expires_at；不可保存明文Token/密钥 |

采用现有可移植SQLAlchemy字段/索引，无MySQL专用DDL；租户相关关联查询显式限制tenant/user，平台级policy在Repository内窄范围bypass，不扩大HTTP请求租户上下文。父子关联不可由客户端指定。表无物理级联删除，客户端/会话缺失必须拒绝；避免修改既有删除/刷新锁序。关联记录不提供管理删除；未来清理只能在child已到期/已撤销后进行，不能使仍有效的交换会话降级成普通会话。

标准API启动/Helm初始化执行alembic upgrade head时自动发现并创建两张缺表；已有表无字段变更，不需要额外revision。直接uvicorn启动仍须先执行正式迁移。回滚旧代码可保留新增表，不做数据回填，不自动给任何组合授权。

## 7. 验证与已知坑

- 单元/协议：严格issuer/audience/类型、source-client绑定、scope交集、固定t0/排队边界、故障拒绝、日志脱敏、普通用户/租户管理员管理拒绝；DB仓储用SQLite验证唯一约束和原子父子记录，用目标DB编译/集成覆盖MySQL/DM8差异。
- 回归：既有Provider三文件43项及request-scope用例；不把未运行的DM8实库测试计为通过。现有decode_access_token会关闭aud验证，不能直接当作交换校验器。管理端全局HTTP异常处理保留HTTP200 envelope，不应把管理拒绝断言成HTTP403/409；测试同时检查业务码。现有ClientFormDialog只在创建时固定code+refresh，编辑时不提交grant_types，因此通过API启用exchange后普通UI编辑不会抹掉该grant（核对handleSubmit:105–130）。
- API E2E：专用A/B和普通用户，经真实issuer完成A授权码登录、交换及参考B验签识别、UserInfo、撤销B不影响A、撤销A后B在线拒绝；客户端停用、关系收窄、输入ID/Refresh/网页/DSH/交换Token都要拒绝。测试fixture按固定前缀清理，保留测试日志，不使用真实业务会话。
- 手动接入：先用管理员客户端API登记confidential A（含exchange grant）与B，再PUT上述policy；A通过正常授权码取得用户Access Token后按§4.1请求。参考B从Discovery取JWKS，检查ES256、issuer、aud=B、exp、token_use及用户/租户；具体可运行示例随实现交付。不向文档写入账号密码/Token。
- A为公开插件时不能塞入client_secret；需独立后端授权方案，本轮不默认信任代理。B本地会话不会随A自动注销，不能把短期Token过期误报成跨系统单点登出。
- 部署issuer取已有public URL解析，A签发和换证必须一致；改域名后旧iss不匹配应拒绝。多节点依赖同一DB/签名配置，不用进程内policy缓存或本地文件作为授权真相。

## 8. 后续与修订

后续若需要公开客户端、外部IdP、业务scope、跨租户或统一B会话注销，应独立评审，本轮不预建框架。初版设计形成于用户接受规格之后；用户确认设计后完成本分支实现。验证范围及尚未执行的线上/DM8实库检查见verification.md。

修订：2026-11-26（America/Los_Angeles），新增标准grant、policy/link、父链校验及测试，依据用户明确的设计实施授权；修正路由生成物遗漏；诊断仅记录异常类型和栈位置，不输出源码行/locals/异常值。无推翻既定设计的偏差。

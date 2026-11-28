# Code Review Report：F003平台统一认证与会话

审查基线：bisheng `572d5ecf77`（feat/3.1.0-alpha1）、mobile `6990f73`（main）。范围：两个实施工作树的未提交差异及新增文件；不以HEAD...HEAD空diff替代未提交文件检查。网关与桌面只读核对，无源码修改。

## 七维度

| 维度 | High | Medium | 状态／证据 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 30/90天、精确失效、策略快照、丢响应/重放、Cookie物理过期、无效body/版本 |
| 权限与认证 | 0 | 0 | 真实密码身份提取，Session/Home/用户版本检查；用途分离、CSRF、凭据冲突；业务权限不改 |
| 并发安全 | 0 | 0 | 用户→Session→Refresh锁序及当前读、唯一代次；Web Locks/IDB/epoch/fence；真实DB锁待用户验收 |
| 信息泄漏 | 0 | 0 | RT/票据只存摘要；网页不返回RT；auth日志不记录query凭据，native Token不注入WebView |
| 测试覆盖 | 0 | 1 | 新平台套件、221前端、209手机及旧组差异对照；本机Jest需可选canvas适配，真实集成用户接手 |
| 代码风格 | 0 | 1 | 架构守卫0发现、Ruff新增0；原有Ruff/ESLint账本问题保持；无全仓格式修改 |
| 设计同步 | 0 | 0 | 实际模块/模型、origin、根auth Cookie路径、父子sid、关闭新签发的回滚地板已同步 |

## 已闭环的问题

- MySQL RR锁后旧快照及identity map：锁定当前读、populate_existing及统一锁序；Tenant使用共享当前读。
- Session策略与单点配置：会话期限快照、登录时读取当前策略；同秒真实JWT使用随机sid/jti；网关选择以私有DB发行序防时间精度与实例时钟差。
- 冻结后的网关绑定恢复补充：事务成功但Cookie/hint响应全丢，仍在首代未消费与300秒窗口内恢复；不得重置已消费链、覆盖更晚选择。
- Access Cookie自然删除仍能凭Refresh恢复；固定入口不遮蔽已选完整Access，迟到绑定不删除另一新入口Cookie。
- 退出先清选择，限定selector恢复CSRF与撤销；重复三次幂等、混传明确拒绝。
- 写事务不使用仅取消等待的to_thread两秒超时；只读准入保持预算，已有流和每条新WS消息都重验。
- 手机RPC真实写方法保活，list/status不保活；真实mobile SSE接入统一守卫，不只测试helper。
- host WebView冷启动Cookie消失后请求原生续期，不清有效parent或发空Refresh；两个SPA初始化和切号查询均门控。
- 两SPA认证固定根/api/v1/auth，避免workspace/custom base使Refresh Cookie不发送；RT/hint按服务器冻结cookie_retention_seconds保留，支持自定义TTL。
- 公开/自证入口忽略无关平台坏凭据，分享缺证明仍403、受保护请求仍401；refresh自行检查混传，不依赖中间件偶然拦截。
- 已提取不签发的PasswordLoginIdentity认证方法；DSH经公开纯状态协议共享轮换，旧表、codec与活动口径不改。

## Overall：PASS_WITH_WARNINGS（本轮开发范围）

没有剩余已知HIGH代码缺陷。警告是已有工具环境/静态基线，不是批准真实环境上线；按用户最新授权，发布前集成由用户自行执行。SQLite串行夹具不能替代MySQL/DM8并发实测；原生DSH安装包和手机真机仍按handoff验收。未合并、未部署。

说明：本报告由主执行者按sdd-code-review清单审查，并结合手机Owner对后端/网页的只读交叉评审；不是外部审计或CI全绿证明。微任务未逐个留存独立红态日志，未伪造TDD历史。

## 2026-11-28 消费者回归修复复审

基线：`origin/feat/3.1.0-alpha1` 的 `ee3e79063f`。本节仅评审本次4项修复及新增回归，不替代上文历史实施记录或整分支验收。按Hotfix轨道完成；接口路径、响应字段、会话期限、权限规则和数据库schema不变。

| 维度 | High | Medium | 结果 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 新旧sid格式、混合分页、重复撤销、Access到期与临时不可用均覆盖 |
| 权限与认证 | 0 | 0 | 当前用户/Home及Desktop类型验证，跨用户/租户拒绝；撤销后应用准入与Refresh均拒绝 |
| 并发安全 | 0 | 0 | 撤销复用已有user→session锁序；宿主补票沿用SDK epoch，退出后的迟到结果不能恢复身份 |
| 信息泄漏 | 0 | 0 | 设备列表仅返回既有展示字段，不暴露凭据；认证失败保持DSH错误封装 |
| 测试覆盖 | 0 | 0 | 新增12个后端参数化场景、3个Provider场景和1个真实SDK状态恢复场景；相关旧组一并回归 |
| 代码风格 | 0 | 0 | 修改Python文件Ruff format/check及架构守卫通过；Client/API-client lint通过 |
| 设计同步 | 0 | 0 | design §5、§6.6同步双会话消费、设备管理、错误映射及冷启动恢复边界 |

### 验证证据

- 后端：`test/platform_auth`、`test/oauth2_provider`、`test/dsh/{test_platform_consumers,test_self_service,test_access,test_web_session,test_platform_ticket_exchange}.py`、`test/cloud_workbench/test_desktop_access.py`、`test/app_publish/test_desktop_publish.py`，320通过、1跳过、3排除。使用已有隔离fakeredis/Lua依赖；未连接业务数据库或Redis。
- 排除项分别是外部双DB用例、需要显式隔离Redis的真实PKCE票据用例，以及 `test_online_seat_check_and_parallel_scopes_are_restored`。最后一项在未修改的 `ee3e79063f` 快照上也单独复现 `None != 99`，属于既有管理作用域测试基线；未把它计为通过。
- 前端：`authStartup`、`requestAuthSession`、`useMobileHostBridge`、`mobileHostBridge` 共27通过；共享包 `authSession`、`authCoordination` 共34通过。
- Client完整lint、共享API-client完整lint和Client严格类型检查通过。类型检查复用现有依赖，临时paths按各workspace包的exports指向本工作树；Jest仅在本机临时禁用未编译的可选canvas。适配文件不进入提交，未改依赖和锁文件。
- `git diff --check`及修改文件的架构守卫通过。SQLite不验证MySQL/DM8锁行为；未部署或执行原生设备验收。

复审结论：**PASS（本次修复范围）**。没有剩余阻塞发现；已知基线失败与外部环境验收限制见上。

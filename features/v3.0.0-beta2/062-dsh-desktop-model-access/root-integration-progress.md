# F062 主线集成进度（2026-09-09）

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

> 当前有效修订：用户确认每用户可配多个模型，各模型独立月额度；一期不做限流，配置使用有字段说明的类型对象。DM8 实机本轮暂缓。最新代码、契约变更及实际验证结果见 [逐模型修订验收](./model-quota-revision.md)。下文保留此前检查时点的证据，测试数量不与新版相加。

用户授权多agent持续开发，E2E环境问题可暂跳过。此文件是阶段证据，不代表功能完成。

## 初期接线记录（历史状态）

- T024/25 身份服务与摘要票据：原子检查绑定后消费、Redis TTL、当前用户/租户强读；真实并发只消费一次。票据寿命补齐min(60,授权事务剩余TTL)，内部resolve增加expires_in。
- T040/41 双向HMAC/Python客户端：固定HTTPS源、exact-body SHA256、instance/key注册、Unix秒±60、共享nonce NX/EX120、不重定向、不接受旧HTTP200错误包装。
- T042/43 专用RS256/JWKS与DshPrincipal：固定issuer/aud/typ、严格claims、普通JWT/PAT/SAK拒绝、逐请求在线验席、tenant/visible/admin/bypass/strict上下文复原。
- T086/87 四身份HTTP端点、DshRoute真实HTTP错误包装和no-store；浏览器JWT及Origin/JSON CSRF、内部HMAC精确body及实例复核。
- T095/97部分接线：全局router已登记四身份端点；精确method/path独立凭证策略，不添加宽泛tenant豁免；四张DSH模型纳入自动tenant发现；可选配置已接Settings，关闭探测不创建依赖，应用关闭释放DSH HTTP客户端。
- 增加独立公钥与用户资料适配器测试；原任务文件清单将在联合审查时补齐实际路径。模型/管理/Worker生产factory和其余端点仍在接线，不宣称已可完整联调。

## 初期验证（历史状态）

- 身份/HMAC/JWT/JWKS/用户适配器+真实MySQL增量DDL：32项通过（后续TTL与HTTP组合回归继续增加）。HTTP最初3项、middleware1项通过，完整应用router可在最小隔离配置下导入四条DSH路由。
- 已建立仅本机的Redis7.2.7与MySQL8独立环境，三个agent用不同库。临时凭据仅保留在0600测试文件，不进入仓库。
- Gateway已跑Maven/真实MySQL抢席测试；配额/策略已跑真实Redis+MySQL事务，具体由各开发线报告给证据。
- 前端依赖已离线复用本机缓存安装；pnpm lint全通过。pnpm typecheck目前有两个既有测试错误，待修（Dashboard旧prop、route filter undefined）；可选canvas原生构建失败，不等于应用构建通过。
- DM8/真实客户旧发行工具/供应商与DSH Desktop全链路环境尚未验证，按环境缺口保留。没有提交、推送或部署。


## 当前增量（16:20 +08，开发尚未收尾）

- 模型三端点已接入 DshModelService 与生产 ModelRuntime。配额激活串行读取不可变审批，失联后不以旧审批自动重连；新月份必须同时满足 SQL 空历史证明与 Redis 永久月份清单校验。
- usage 将内部状态映射为冻结的 live/persisted/unavailable 与 available/exhausted/unavailable。没有可信快照时 used/remaining/as_of 保持 null，SQL 旧快照不会用于放行模型。
- DshStreamingResponse 在响应头发送前断线也关闭 PreparedStream；每次 anext/aclose 独立恢复 tenant 与 trace 上下文，trace_id 与账本 request_id 对齐。遥测新增 DSH_DESKTOP，统计失败不回滚已落账结果。
- 浏览器 authorize 增加可选 decision=deny，安全解析原事务后返回 access_denied/redirect_uri/state，不签票据；7 个 Desktop 接口和原拒绝回调不变，client-api/design 已同步。
- admin router 与生产 CLI runtime 已挂入主线；Celery 实际注册由 quota 线接入。管理与后台恢复仍在联合审查。
- 模型 HTTP/认证/中间件组合 21 项通过；遥测/实际 LLM wrapper/模型HTTP/浏览器HTTP/票据组合 31 项通过；ModelRuntime 并发激活与丢月账本拒绝 2 项通过。这些集合有重叠，不作简单相加。
- 前端两项历史类型错误已修正为当前懒加载权限语义与精确 string 过滤，相关 11 项 Vitest 通过；本轮 pnpm typecheck 通过。UI agent 仍在新增 DSH 页面，最终检查待其完成。
- Gateway 本地 DshActivationCommand 新增 pause/status/resume，显式 Redis 配置，不提供伪造 ACK 或强制排空；2 项命令测试 + 1 项原激活测试实际 Redis 全绿。可执行打包因公共 Maven 依赖 TLS 下载失败暂在恢复下载，不属于编译失败。

## 最终集成复核（2026-09-09，覆盖此前阶段记录）

两仓核心代码与 Platform 已接线；没有提交、推送、合并或部署。代码检查、外部 Desktop/供应商联调、目标旧二进制、DM8 与部署性能验收分别记录，不将后者标成通过。

- Python 实际 15 端点与 Gateway 11 端点保持 26 个总数；客户端仍为 0.1.0 的 7 接口/7时序图，单 Nginx origin。用户资料、现有 SSO/主部门变更同事务投递；管理权限使用既有全局/租户管理能力。
- 完成 HTTP 200 管理错误证据保留；Gateway License/disabled 明确拒绝持久 FAILED；操作恢复以原 intent 重放验证 hash 后才采信终态。网络不确定不变成假失败或假成功。
- 资料按条数与精确 JSON 字节拆批；Java Unicode 与 255 字符原用户模型兼容。配额清单按 500 条/4 MiB 分片，10,001 请求完整恢复及缺片拒绝有真实存储测试。
- 最终 Gateway **45 tests passed，0 failure/error/skip，package BUILD SUCCESS**；此前额外一次 50,000 席位规模用例通过。可执行 JAR 已含激活 CLI 和最终修复。
- 最终 Platform **38 tests passed**，前端全仓 lint/typecheck/check-i18n 通过。新增页面未引入库或改共享视觉规范；两个基线测试错误已按当前行为修正。
- Python 联合套件 **232 passed、14 setup errors**；setup 是 fixture 安全拒绝非指定/已有表测试库，保留保护后在独立空库补跑对应 5 文件，**22 passed in 17.20s**，覆盖上述 setup 阻塞；数据库前后均为空，详见 database-acceptance。管理 Saga 最终专项 **49 passed**，与全套有重叠，不简单相加。
- 真实 MinIO 4 项、多进程故障验收 1 项通过。E2E 安全门 3 项通过，真实部署 7 项因配置缺失跳过；用户授权允许暂跳过环境阻塞 E2E。
- Ruff 通过；Architecture Guard 对 139 个修改/新增代码文件检查：0 VIOLATION，2 条 WARNING 分别是原配置和显式假密码测试。两仓 diff-check 通过。
- Design、HTML、tasks、client-api、客户端交接/现场清单、rollout 及兼容/数据库/恢复/代码评审报告同步。部署必须先补齐各报告中未关闭门禁；本轮不宣称生产 SLA 或旧二进制兼容已验证。

## 完成性复核增量（2026-09-09）

本轮修复管理 GET policy 的目标租户、受管候选模型及最后调用摘要；明确权限/模型拒绝持久失败而非无限 PROCESSING；成功席位操作写入前后 state/grant_version 审计。管理策略/视图/API 联合 51 项通过，管理操作/视图/API 联合 35 项通过，包含真实 MySQL/Redis；两组有重叠，不相加。Platform 12 文件 42 项通过，lint/typecheck/check-i18n 通过。Gateway 最终 48 项测试与 package 通过。配额完整增量见 python-quota-progress.md 与 completion-audit.md；环境门禁保留。

# F111 DSH 敏感词控制发布与回退草案（待隔离演练）

日期：2026-10-24。此文件为实施过程留档的待执行草案，不是已执行发布记录，不授权部署、生产迁移或删除。T131 依赖 T129/T130；本次只读准备不满足这些前驱，不勾选 T131。

覆盖 AC: AC-02、AC-03、AC-04、AC-11、AC-12、AC-16、AC-17、AC-32、AC-43、AC-51、AC-54、AC-55、AC-58。

## 1. 证据和状态边界

| 项目 | 当前状态 | 本草案能够证明的范围 |
| --- | --- | --- |
| 当前配置、注册、CLI、DDL、回退代码逐项读取 | READ_VERIFIED | 文件确有相应实现；不是线上有效配置或现场演练证明 |
| Backend T119 MySQL 隔离库 | 已有组件证据：16 PASS | MySQL 8.0.46、PyMySQL 1.1.2、SQLAlchemy 2.0.44；fresh 与真实 work110 archive 升级后 144 表结构一致、F111 head、事务/保留测试；不替代发布演练 |
| Backend Linux DM8 | NOT_RUN | 未具备真实 Linux DM8 环境，不用其他数据库结果替代 |
| Gateway T120 MySQL SQL片段 | 主独立10 PASS，DM8 NOT_RUN | 两独立全新库实测；小表计划/锁及进程恢复证据见verification，不替代部署演练 |
| 跨仓 E2E、容量、发布回退演练 | NOT_RUN | 最终状态由implementation-verification.md登记，不从源码或本草案推断通过 |
| 入口封闭、防旁路、时钟、真实 worker/Beat、真实租户策略切换 | NOT_RUN | 必须到拟发布隔离拓扑逐项记录 |

后续每个执行步骤须填写操作者、时间、仓库 artifact SHA/镜像 digest、数据库方言/版本、受控证据路径、PASS/FAIL/NOT_RUN。不要把密钥、Token、Cookie、License 内容、完整连接串或模型原文写进证据。此草案没有读取应用 License 密钥。

## 2. 发布前硬门槛（均为 NOT_RUN）

1. 确定实际 Gateway、Backend API、全部原生审计写入者、Celery 默认队列 worker、Beat、Platform、Desktop 版本和部署拓扑。三仓当前未提交工作树不是可发布 artifact；先经正式交付流程产生可追踪 artifact。
2. T129/T130、所用方言数据库闸门、E2E 和容量结果未完成时不能宣称已具备上线条件。Linux DM8 现场必须独立验收，MySQL 通过不授权 DM8 启用。
3. 确认可恢复备份/恢复演练和数据库操作权限；敏感词表和 Outbox 都属于保留数据。回退不把删表、删事件或清水位作为常规操作。
4. 盘点所有公开域名、代理、LB、路径重写、Desktop 自定义 Base URL、直连 IP/端口、IPv4/IPv6 和旧入口。只有 Gateway 的两种模型 POST 入口应可由客户端触达；Backend 模型端口只允许可信 Gateway/管理网络。
5. 所有节点 NTP/系统 UTC 对时，记录偏差；回传允许发送时间 ±300 秒不是允许时钟失控的运维指标。
6. 各 Gateway 副本使用相同的 Backend 目标、`backend-namespace`、稳定 `source-id`、内置词库文件及摘要。namespace 要区分不同 Backend 部署；不要在进程重启、扩容或回退时临时更换 source-id，导致历史事件来源/缓存空间变化。
7. 先完成全部原生 writer 和安全接收端的删除水位保护再允许 `purge-audit --apply`。代码端口为 `lock_retention()`：缺行先创建/flush，设置行锁在主行锁之前；保留闸门覆盖原生 writer、新事件及重复补报合并，不能只升级 API 漏掉旧 worker。
8. 不启用任何自动明细保留周期。当前默认不清安全明细；30 天是设计容量示例，不是落地清理配置。

## 3. 配置核对（READ_VERIFIED；有效部署配置验证 NOT_RUN）

| 配置/目标 | 实际入口 | 要求 |
| --- | --- | --- |
| Gateway 总开关 | `dsh.content-safety.enabled` | 默认 `false`；开启是部署配置变更，不假定现有代码支持热刷新 |
| 稳定身份 | `dsh.content-safety.backend-namespace` / `source-id` | 默认空；开启时必须显式、格式合法且稳定；不能让用户请求覆盖 |
| Backend origin | Gateway `bisheng.bisheng-api-url` | 既有配置；仅 HTTP(S) origin，可无 path 或 `/`，不能带凭据/query/fragment；profile、模型代理、回传共同固定到它 |
| 共享 HMAC | Gateway `bisheng.gateway-hmac-secret`；Backend `sso_sync.gateway_hmac_secret` | 必须同一已存在的共享值，安全配置注入，不打印或保存明文，不引入 DSH 新密钥/key_id |
| 既有环境变量 | Gateway 示例 YAML 引用 `BISHENG_GATEWAY_HMAC_SECRET`；Backend 支持 `BS_SSO_SYNC__GATEWAY_HMAC_SECRET` | 只登记变量名；不能为了排查而 `env`/`printenv` 输出值 |
| 签名头 | Gateway `bisheng.signature-header`；Backend `sso_sync.signature_header` | 默认双方 `X-Signature`；定制时双方一致，走同一个已批准的变更 |
| Gateway HTTP 期限 | `spring.cloud.gateway.httpclient.response-timeout` | 启用前必须为正；Docker 挂载示例为 `3600s`，不是推荐 SLO。源码 resources YAML 未给这个值，不能假定所有部署都已有 |
| 内置词库 | 既有 `custom.sensitive-words-path` / 既有词库加载路径 | 各副本内容/摘要一致；缺词库、摘要不一致或读取失败不能视为租户关闭而放行 |
| 管理站点 | Gateway `bisheng.home-url` | 管理 PUT 要求合法同源 Origin；不以 DSH Token 取代实时管理员授权 |
| Backend DSH/Beat | `dsh.enabled` / `dsh.audit_state_scan_interval_seconds` | DSH 默认关闭；既有使用 DSH 的环境保留其正常业务开关。Beat 安全扫描在 `dsh.enabled=true` 时注册，默认间隔 60 秒，支持 10..3600 秒 |
| 租户范围 | Backend `multi_tenant.enabled` | 关闭时只接受现有默认租户 1；开启时共享 HMAC 代表本 Backend Gateway 服务，但每条事件仍严格单租户。source-id 不是权限白名单，也不检查当前用户/租户 active 来拒绝历史事实 |

SSO 登录本身不需要开启，`bisheng.enable-sync` 也不是 DSH 回传前置。共享 key 未配置只使回传接收不可用；Backend 模型鉴权/额度/计量不新增 Gateway/HMAC 运行时依赖。不要读取或改动应用 License 密钥；商用 Gateway 的既有能力准入只能验证其结果，不能在此流程绕过。

## 4. 精确启用顺序（以下执行均 NOT_RUN）

### 4.1 先扩 Backend schema、兼容读取、保留保护

Gateway 检查保持关闭。在所用方言备份和前驱通过后按已有发布流程更新 Backend artifact，再从 `src/backend/` 用现有安全配置运行：

```bash
uv run alembic heads
uv run alembic upgrade head
uv run alembic current
```

预期唯一 head/current 为 `f111_dsh_content_safety`；本次不能照抄早期设计的 work110 head。在线升级先真实模型发现/create_all 创建缺表，再执行扩展既有表的 revision；不要用 `create_all` 冒充修改已有列、用 `stamp` 冒充升级，或在迁移里回填业务数据。复跑检查结构等价，不把 `IF NOT EXISTS` 视为漂移修复。

检查 `dsh_content_safety_event` 新表、主审计安全摘要/来源/可空模型轴、树/设置水位及约束/索引。老 MODEL 行原有模式和未知用量保留，EXTERNAL_SAFETY 可以无 mode/session/manifest/key，不能捏造执行结果和用量。先确认全部 writer/接收端水位保护已生效，暂不清理。

### 4.2 启动并验证独立投影/默认队列/Beat

沿既有部署编排启动/更新，不在本草案创建新部署。仓库实际使用的入口为：

```bash
uv run celery -A bisheng.worker.main worker -l info -P threads -Q celery -n celery@%h
uv run celery -A bisheng.worker.main beat -l info
```

生产并发数沿现有审核配置，不把上述省略项当容量建议。已有 `task_routers` 可覆盖队列；必须检查最终路由和实际消费队列，而不只启动 knowledge/workflow worker。Beat 应只有规划中的活动调度实例，避免复制部署误建多个调度器。

确认注册 `dsh.scan_content_safety` / `dsh.project_content_safety`，Beat 条目 `dsh-content-safety-projection` 使用扫描间隔。扫描只按 dirty tenant IDs 分页，每页100；可重扫已停用/归档租户的历史，单租户 project 通过 Celery `headers.tenant_id` 与任务参数精确匹配。禁止绕过信号/直接伪造事务来“修”上下文。

按需先 dry-run，再在隔离演练授权下有限重建：

```bash
python scripts/dsh_content_safety_maintenance.py rebuild --tenant-id "$TENANT_ID"
python scripts/dsh_content_safety_maintenance.py rebuild --tenant-id "$TENANT_ID" --apply --batch-size 100 --max-batches 20
```

有 `next_cursor` 按同 tenant 的 `--cursor` 续跑；`examined` 含 `skipped_expired`，不能叫“恢复条数”。必要时使用已有 `prepare_dsh_audit_tree.py --tenant-id ...` 的默认 dry-run/独立 apply 步骤，不能越过 BUSY 租约。

以真实管理员在 `/api/v1/dsh/admin/model-audit/query-readiness?tenant_id=...` 检查 `safety_ready`、`safety_summary_version`、`safety_summary_as_of`、`summary_ready`、`indexing_pending` 和构建 phase。不能把 API 200 或版本0当已就绪；0 是合法已发布版本，需同时满足真实 published_at、水位一致、无 pending/failed。worker 停止后新命中迟到必须显示未就绪并能恢复收敛，不应伪造当前 as_of。

### 4.3 发布 Platform / Desktop，再部署 Gateway（保持总开关 false）

先验证 Platform 外部记录 N/A/未知/已清理与命中过滤、Desktop Chat/Responses content filter 文案和真实工具屏障，然后发布 Gateway。

Gateway DDL 用所选方言的实际脚本：

- MySQL：`docker/db/f111_dsh_content_safety_mysql.sql`（8.0.16+ CHECK 生效；本地已验版本另见 T120）。
- Linux DM8：`docker/db/f111_dsh_content_safety_dm.sql`（CLOB/TIMESTAMP(6)、schema owner/disql；当前 NOT_RUN）。

先确认目标现有 Gateway schema，再按 DBA 工具加载，不在命令行携带密码。已有表须完整核列/约束/索引，不能靠脚本跳过表示一致。两个表为 `gt_dsh_sensitive_policy`、`gt_dsh_safety_outbox`，均不存 Token/原始命中正文。

确认实际生效配置包含两条 order=-10、`Method=POST`、Path `matchTrailingSlash:false` 的专用路由，目标为 `${bisheng.bisheng-api-url}`，没有 `CacheRequestBody`。文件来源分别为 `src/main/resources/application.yml` 和 `docker/gateway/config/application.yml`；`src/main/resources/application-dm.yml` 是方言覆盖，不能当作单独完整路由配置。

总开关 false 时预期原 DSH 模型透传；配置完整时 management/Outbox 仍创建且补报运行，检查 Bean 不创建。配置不全时 capabilities 要如实不可用，不能显示虚假的关闭可用状态。

### 4.4 HMAC、入口和回传闭环

验证以下真实网络路径，所有结果为 NOT_RUN，不能仅用单元测试替代：

1. Gateway 使用原 Bearer 调用固定 Backend `GET /api/v1/dsh/profile`；身份来自 Backend 可信结果，不能只解 Token claim 推租户。缓存正例最多共享30秒、本机2秒且受 Token 截止减5秒约束；未知截止时间不缓存；miss 的1秒总预算含排队，32在途/64等待。模型转发仍把原凭据交 Backend 重新准入。
2. 回传为固定 `POST /api/v1/internal/dsh/content-safety-events`，无 query。UTF-8 JSON envelope 为 `sent_at` 和原始 `event`；HMAC-SHA256 对 `upper(METHOD) + LF + PATH + LF + raw_body` 签名，默认小写 hex。PATH 不含 query；重试只换 sent_at/签名，不改 event、原 null/missing、时间拼写或 payload hash。
3. 由真实 Gateway dispatcher 对合成演练事件完成回传，观察精确200、`receipt=COMMITTED`、event_id 匹配才 ACKED；重复相同事件返回 duplicate 且不重复计数。仅 HTTP2xx、内存队列成功、响应编号不匹配、伪回执都不能算 ACK。
4. 无签名、只有浏览器 Cookie/用户 Token、错误 key/签名、超时窗应拒绝；GET 非注册方法、query 参数、超过64KiB envelope、重复 JSON key/坏 UTF-8 有安全拒绝。单租户的其他tenant拒403；拒绝不应触业务 SQL 或泄露原正文。不要把这些负例写进真实业务审计。
5. 外部网络用**有效演练 DSH 凭据**分别尝试直连 Backend 两个模型 POST，网络层必须不可达，而非仅401/403；有 Token 时能直连就仍有旁路。覆盖所有公开LB、旧域名、IP、IPv6、改写入口及等价编码/matrix路径，且合法规范路径确实经过同一检查。
6. 登录、刷新、profile、模型列表、用量查询不作为内容检查对象；普通 Gateway 应用/旧敏感词功能保持原路由和语义。回归无 Gateway 的 F110 登录、模型、用量能力，确认 Backend 没有新增 Gateway依赖。

所有 HTTP 凭据从0600临时认证文件或既有受控测试工具注入，不在 curl 参数、终端历史/trace、文档保存。回传测试使用现有真实 client/dispatcher，不临时加后门 endpoint 或手工改 Outbox payload。

### 4.5 测试租户开启，再逐租户扩大

使用真实租户管理员经 Gateway 的 `GET /api/sensitive/dsh/capabilities?tenant_id=...` 和 `GET/PUT /api/sensitive/dsh/settings?tenant_id=...`，普通用户/其他租户管理员无权越租户。capabilities 应显示 configuration_ready、available 与一致的 builtin_digest。PUT 要求实时授权、合法同源 Origin、`expected_version`；冲突重新读，不盲重试覆盖。

先保存测试租户有效词库（内置/自定义源、auto_reply、输入/输出方向），租户 enabled 保持 false；未配置租户默认关闭。在通过入口封闭和配置校验后，将部署总开关设 true 并按已有流程平滑更新 Gateway。此时非试点租户保持关闭，再保存试点租户 enabled=true。版本、开关、方向、词库/提示原子提交，新请求最多5秒生效，在途保留进入时的快照。

至少实际验证 Chat 非流/流与 Responses 非流/流、输入/输出两方向、跨分片Unicode、工具参数完整/截断/错误终态、正常不命中、租户隔离、失败不可伪装关闭、后端执行/交付/计量独立。输入阻断只产生外部安全审计，不伪造 backend 执行；输出阻断立即停客户端交付，后台续读最长从命中起30秒且受容量/字节/异常提前截断，真实用量可晚到/未知，不能写0或宣称供应商已停止。

## 5. 观察和放量条件（现场 NOT_RUN）

当前真实 exporter 为 `DshSafetyTelemetry` 的固定枚举日志快照，不声称已有 Prometheus/Actuator endpoint。检查 PROFILE_HIT/MISS/MERGED/ERROR、PROFILE_ACTIVE/PROFILE_QUEUED/PROFILE_LATENCY_NANOS、POLICY_DIGEST_MISMATCH、CHECK_HIT/ERROR、COMPILE_REJECTED、ENCODED_BUFFER_BYTES、CHECK_ACTIVE、DRAIN_ACTIVE、RECORDING_GAP、Outbox pending/inflight/quarantined/oldest-age/last-success。

源码预算：32MiB请求/累计响应、Responses单事件8MiB、全局64MiB编码额度、16检查/8续读、匹配器缓存128MiB；这是 admission 上限，不是 RSS 上限、吞吐保证或可承诺SLO。实际 HTTP writer 未完成持有的 bytes 计入预算；慢客户端不能提前退额。JVM解析树/字符串放大、数据库锁/索引开销、profile未命中负载及双库百万/千万数据查询 p95/p99 均引用 T126–T129 **待测**结果，未测不填数值结论。发现缺口/隔离/磁盘压力立即停止放量并保留证据。

默认列表不返回/扫描明细来计算主命中；详情按需加载。表独立不自动证明容量；默认7天/最多31天查询窗口、移动窗口和显式筛选绑定游标仍须执行计划/扫描行数实证。

## 6. 应用回退（NOT_RUN；默认不做结构收缩）

1. 优先在当前兼容 Gateway 上关闭试点/所有已启用租户策略，记录新版本；等待最长5秒的新请求生效窗口，验证新请求停检查。在途保持原快照，不因关闭改词库或抹掉已发生事实。
2. 如需部署总开关 false，按现有平滑更新流程操作。没有热刷新保证；先记录在途请求/检查/续读/HTTP writer 状态并等待安全退出。30秒只约束**已命中后的后台续读**，不是所有模型请求或慢 HTTP writer 的总退出时间，不得按30秒强制认定已无在途。
3. 保持稳定 namespace/source/key/header/固定目标、DB两表和全部 pending/lease 状态。总开关 false、租户 false 不停止独立补报器；重启后过期 lease 可恢复领取。PENDING/INFLIGHT/QUARANTINED 不自动删除，错误隔离不是成功；ACKED 只有正确提交回执才设置，当前 acknowledged 清理保留7天且有界。不得为清空积压改ACK或改payload。
4. Backend 接收与投影 worker 保持可用，直到当前未确认事件和后续在途产生的事实完成处理。若回退到**不含补报器的旧 Gateway**，必须先在现有兼容实例保留补报服务能力或明确登记投递暂停，不能宣称旧版本仍会自动补报；历史表不能删除。若 Backend 旧版不含接收路由，回传会重试，不能把404当ACK；避免先撤接收端导致持续积压。
5. 旧 Backend/旧 DTO 回退须先实测 EXTERNAL_SAFETY 的 nullable mode/session/轴、N/A、未知/已清理，以及已有安全列/树水位兼容。未有兼容证明则阻止旧 DTO/旧 writer 回退，而不是把外部记录改MODEL或删掉。回退不得丢失原生writer删除水位保护；清理水位持久且单调，不能清零来使旧writer继续写。
6. 保留 Backend 安全表/摘要列/设置水位、Gateway policy/Outbox、原审计证据/对象/密钥、DshModelCall、DshMonthlyUsage及独立计量链。输出命中不等于未消耗额度；UNKNOWN不能被回退脚本改0。原生body/manifest/object可能共享，不属于本流程可销毁对象。
7. 恢复同一兼容版本后，保持 event_id/payload/hash，重复投递幂等；先检查积压和隔离，恢复 worker 收敛 readiness，再评估重新启用。不要清空缓存/水位或重建新source来掩盖故障。

Backend 的 F111 Alembic `downgrade()` **无条件 RuntimeError 拒绝**，即使空库也拒绝。已有真实MySQL测试验证空/有事实均不改schema，populated还保留完整Fact/Request/Call/Monthly业务快照。回退应用保留F111 schema/事实；不使用 `alembic downgrade`、`stamp` 或手工删列冒充支持回退。

## 7. 仅空测试 schema 的结构回退（单独删除授权+演练；NOT_RUN）

此节与常规应用回退分开。执行前停止**全部副本**管理/策略写入、模型检查、Outbox发送/ACK清理、Backend接收/原生writer/投影及相关维护，网络确认不会新进写；单改enabled=false不满足停写条件。取得独立删除授权和可恢复快照。ACKED即便已投递仍是表内数据，不能为了判空先清掉。

Gateway已有真实脚本（MySQL隔离SQL验证已由T120执行，以下部署演练仍未执行）：

| 方言 | 脚本 | 保护 |
| --- | --- | --- |
| MySQL | `docker/db/f111_dsh_content_safety_mysql_rollback.sql` | 必须同一连接先 `SET @f111_writers_stopped = 1`，否则拒绝；检查 policy 与 outbox 两表 COUNT，任一非0在任意DROP前拒绝；两个都空才先Outbox后Policy；需临时CREATE ROUTINE权限 |
| Linux DM8 | `docker/db/f111_dsh_content_safety_dm_rollback.sql` | 默认本地 `writers_stopped INTEGER := 0` 拒绝；只在隔离停写确认后受控临时副本改为1，以schema owner/disql执行；USER_TABLES+两表COUNT，任一非0在任何DROP前拒绝；当前真实环境 NOT_RUN |

MySQL DBA 会话示意，仅作为未来隔离演练记录模板，**本次未执行**：

```sql
SELECT DATABASE();
-- 独立核对批准的唯一隔离 schema、全部写入者已停、两表真实为空后：
SET @f111_writers_stopped = 1;
SOURCE /approved-artifact/docker/db/f111_dsh_content_safety_mysql_rollback.sql;
```

必须分别演练：默认无停写确认拒绝；Policy非空/Outbox空拒绝；Policy空/Outbox非空（含ACKED）拒绝；双非空拒绝；双空且已停写才删；核对失败前后两表/原业务表及完整数据快照不变。脚本的ack变量不自动锁住其他写入者，停写是操作方真实前置，不能用写1代替。

Backend **没有本特性可直接执行的空库收缩脚本**；F111 downgrade 的拒绝不能靠修改 revision 绕过。后续T131若要演练Backend空schema物理收缩，需单独可审DBA步骤：全模型/接收/投影停写、确认受影响新增表和列无事实/非默认业务数据，列出完整逆向DDL与约束顺序、双库验证和恢复路径。当前该部分为 NOT_RUN/步骤待制定，不提供猜测DM语法或不带保护的DROP。

## 8. 明细/主审计保留运维（可选，默认不执行）

命令从 Backend `src/backend/` 运行，沿现有服务 `config` 配置；参数仅演示变量，不提供真实tenant/日期/凭据。所有命令默认dry-run，检查配置/tenant并报告计划，不扫描业务数据，因此dry-run输出不是待清理/可恢复条数。

```bash
python scripts/dsh_content_safety_maintenance.py purge-details --tenant-id "$TENANT_ID" --before "$UTC_CUTOFF"
python scripts/dsh_content_safety_maintenance.py purge-audit --tenant-id "$TENANT_ID" --before "$UTC_CUTOFF"
```

明确保留审批和恢复要求后才加 `--apply --batch-size 100 --max-batches 20`。UTC_CUTOFF必须带时区，内部归一UTC、exclusive；batch1..100/max-batches1..10000。`purge-details`显式include_audits=False，不消费既存主清理水位/cursor，保留命中摘要与PURGED语义。`purge-audit`先独立提交单调删除checkpoint再有界删除主行和其关联安全facts，同事务更新汇总；未关联facts不误删。运行中/未结算行跳过，结束后同cutoff再跑可重访，即使上一轮has_more=false。

失败batch全部回滚，早前已提交batch和checkpoint保留；JSONL只有commit成功后输出，丢输出可以幂等重试。CLI退出0成功、2参数/请求错误、3配置/依赖、4无tenant、5运行失败。只清主审计/安全事实，不回收原生子表元数据、共享原文对象/密钥或模型调用/月用量。重建仅已有完整事实且水位允许范围；已删事实不承诺恢复，过期缺主不得复活。

## 9. 演练结果待填清单

- [ ] NOT_RUN：实际artifact/config生效来源、目标origin、共享key一致性（只记录校验结论）、签名头、NTP。
- [ ] NOT_RUN：全部公开Chat/Responses流/非流入口、等价路径、带有效Token的Backend直连网络拒绝。
- [ ] NOT_RUN：真实HMAC回传/重复/ACK丢失/重启、检查关闭仍补报、不可恢复隔离和磁盘告警。
- [ ] NOT_RUN：真实worker/Beat/tenant header/停止恢复、迟到命中dirty重新发布、安全readiness。
- [ ] NOT_RUN：Platform授权与筛选/跨租户、Desktop真实工具屏障、旧应用/无Gateway回归。
- [ ] NOT_RUN：各副本词库摘要、租户CAS/5秒生效/在途快照、profile负载和失效。
- [ ] NOT_RUN：T126–T129容量、锁/scan/p95/p99/堆放大与支持负载；不编SLO。
- [ ] NOT_RUN：检查关闭/应用回退/接收保留/旧DTO兼容/水位保护/积压恢复。
- [ ] NOT_RUN：Gateway双库空表收缩与任一有数据拒绝；Backend独立空schema收缩步骤仍待评审。

## 10. 当前读取的代码锚点（仓库相对路径）

Backend：`bisheng/dsh/content_safety_runtime.py`、`dsh/api/endpoints/content_safety_events.py`、`dsh/api/endpoints/model_audit_admin.py`、`dsh/domain/services/model_audit_queries.py`、`dsh/domain/repositories/model_audit_write.py`/`content_safety.py`、`bisheng/worker/config.py`/`dsh/content_safety.py`/`dsh/registry.py`、`core/config/sso_sync.py`/`dsh.py`、F111 revision、`scripts/dsh_content_safety_maintenance.py`及README。

Gateway：`DshSafetyProperties`、`DshSafetyBeansConfiguration`、`BishengConfig`（只读字段定义，未读取License值）、`DshSensitivePolicyController`、`DshContentSafetyFilter`、`DshProfileClient`、`DshModelProxyClient`、`ContentSafetyEventClient`、`DshSafetyOutboxDispatcher`、`DshSafetyTelemetry`、两份application.yml路由/DSH配置及四份F111双库DDL/rollback SQL。

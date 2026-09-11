# F062 部署与回退操作说明

本文交付运行接线，不表示已部署。BiSheng 分支 `feat/3.0.0-beta2-pre`；Gateway 分支 `feat/dsh-access`。执行前使用正式发布制品与本环境自己的 Secret；以下均为配置结构，不含真实凭据。

## 入口与相互信任

客户端只配置一个 HTTP 或 HTTPS Nginx origin。Nginx 的 `/api/*` 进入 Gateway；Gateway 的版本化 `/api/v1/*`、`/api/v2/*` 进入 Python。页面由平台 SPA 提供 `/desktop-login`。DSH 模型流不得经过旧响应包装或整段缓存，Nginx 也应关闭对应 SSE 缓存并允许长连接。

两服务的内部地址使用固定 HTTP/HTTPS origin；HTTPS 仍校验证书。109 联调使用 HTTP，公开地址为 `http://192.168.106.109:13001`，无证书导入要求。仅复用原用户同步的一个共享 Secret，不另配双向 HMAC、Token 公私钥或 issuer；两端派生规则见 [部署配置简化](./deployment-simplification.md)。

| Python 配置 | Gateway 配置 | 约束 |
|---|---|---|
| dsh.platform_public_url | bisheng.home-url | Gateway 提取 home-url 的协议、主机与端口，生成客户端可访问的授权页地址 |
| dsh.gateway_internal_url | bisheng.bisheng-api-url | 分别指向 Gateway 与 Python 的内部 HTTP/HTTPS origin |
| sso_sync.gateway_hmac_secret | bisheng.gateway-hmac-secret | 现有共享 Secret |
| settings.redis_url | Gateway 原 Redis 配置 | 不新增 DSH Redis 地址 |
| dsh.billing_timezone | — | 默认 Asia/Shanghai |
| — | dsh.license-verification-keys | 既有 License 扩展验证，与 HMAC 分离 |

Gateway 升级前删除旧 `dsh.public-origin`、`dsh.python-origin`；DSH 配置采用严格绑定，遗留字段会导致启动失败。原 `bisheng.home-url` 的页面路径、查询参数与片段不进入 DSH 授权链接；SSO 原有使用方式不变。客户端接口无变化。

移除旧 quota_evidence_bucket、quota_approval_object、quota_approval_sha256 配置；DSH 不再依赖 MinIO 恢复材料，严格配置绑定不接受旧字段。dsh.enabled 默认关闭。

## 数据与服务启动

1. 备份两个业务库。Gateway 按方言执行 `docker/db/update_dsh_mysql.sql` 或 `update_dsh_dm.sql`，仅新增四张 DSH 表及索引；脚本遇到已有对象会失败，必须先核对已部署 schema，不能通过删表重跑解决。未发布的本次草案投影列由 128 扩为 MySQL 510 字符 / DM8 2040 字节；DM device_label 由 128 扩为 400 字节以容纳 100 Unicode 码点；如果先前手工执行过草案，先只读核对两个姓名字段与索引，再做保留数据的扩列迁移。
2. Python 四张独立表进入既有模型发现/create_all 流程；原 User 表通过正式 `v3_0_0_f062_profile_version` revision 增加版本列。按现有 Alembic 发布流程执行，保留版本链；不重置已有资料版本或配额历史。
3. 复用毕昇既有 Redis 连接配置。当前 DSH 受控连接支持单实例/Sentinel，不支持 Cluster。不要为 DSH 修改共享实例的淘汰策略；首次开通与丢账恢复自动读取 SQL，并合并尚存 Redis 记录。
4. 保留现有 SQL/Redis 数据；不需要创建 DSH MinIO 桶或确认对象。历史对象可留存备份，应用不会删除。
5. 在毕昇模型管理中配置供应商及模型，再通过 DSH 界面配置用户每模型授权和月额度。不再填写模型部署白名单。

6. 部署 `dsh.enabled` 默认 false；部署者开启后，超级管理员进入 DSH 管理页启用业务开关，并保存本组织受控的无凭证 HTTP(S) 下载地址。业务开关默认关闭，旧部署开关为 true 不会自动开启业务。未配置时页面保留联系管理员和手动填写平台地址，不能交付虚构链接。下载包和自定义协议注册由 DSH Desktop 项目提供。

## Gateway License 加载与更新

不配置 installation_id 或 replica-id，不执行激活命令、暂停/ACK/恢复流程。沿用既有 License 配置入口，各 Gateway 加载并验证自己当前配置的 schema 2 License，依据本地有效期及席位上限处理请求。K8s 滚动更新期间允许短暂版本不一致；升级全部完成后，各副本使用目标配置。

同环境所有副本从共享数据库统计 ASSIGNED 席位，通过原有事务与锁串行控制新增分配。假设旧副本上限为 10，新副本上限为 2，已用 2 席时新副本拒绝新增，旧副本仍可能分配至 10；更新不自动回收已有席位。不同环境使用独立数据库/Redis，同一 License 分别控制各环境的席位数。

指纹输入保留，但不匹配运行环境。公钥只用于验证发行签名，旧 SSO/trial/pro 逻辑保持。删除的旧共享激活 Redis key 不再读取，不需要通过手工修改 phase 来开放服务；历史 key 可在核实没有旧版本服务后按原命名空间清理。

此次内部协议与表结构切换仍须遵守 [安装标识解绑修订](./installation-unbinding-revision.md) 的备份和配套更新步骤；这属于一次性测试版格式切换，不是以后每次更换 License 的要求。额度账本改为 SQL 自动恢复，不再配置 MinIO 审批。

## 配额首次初始化和持续运行

管理员正常保存初始模型额度策略，系统自动从 SQL 初始化账本并完成同一操作。无需手工执行 initialize、填写确认文件或手写 SQL。

普通后续用户由同一已批准账本上的策略事务自动创建 version 0 gate，再安装目标策略；月份切换由 SQL 空历史和 Redis 永久月份记录共同证明，不会抹去跨月 UNKNOWN。Worker 实际注册 `dsh.project_usage`、`inspect_usage`、`reconcile_usage`、`resume_operation`、`scan_operations`、`scan_profiles`、`scan_usage`；启用时 Beat 派发投影、巡检、操作恢复和资料补偿。保持现有队列与单一 Beat 调度部署纪律。

Redis 不可用期间返回额度不可用；连接恢复后自动核对/重建。重建以 SQL 已落库数据和 Redis 尚存记录为依据，无法找回的异步尾部用量接受丢失。SQL 降级展示仍标记 persisted/unavailable，不直接作为实时准入接口。详见 [SQL 自动恢复修订](./sql-quota-recovery-revision.md)。

## 联调与回退

先完成 [客户端交接清单](./desktop-handoff-checklist.md) 中登录、刷新、退出、两个角色范围、流取消和故障场景。查看 DSH request_id 对应的 SQL 明细、Redis 投影积压和 `dsh_settlement` 日志；日志不得记录 Token、完整消息或票据。遥测不是硬账本。

回退时先停止新 DSH 准入，保留已分配席位、会话/refresh 摘要、审计和配额数据，妥善结算在途请求。关闭开关仍保留原用户同步共享 HMAC Secret，使本版 DSH 凭据可退出；DSH Token 不再配置公钥或私钥。License 验证配置继续独立保留。Python/Worker 停止后不删除 Stream、AOF 或证据。旧商业授权的有效性继续按原字段计算，不因 DSH 关闭延长或缩短。

仍未完成的环境/制品验收以各 acceptance/report 为准。本文不授权发布、生产数据修改或对外发送文档。

## 逐模型配置修订的发布准备（2026-09-09）

- 主配置使用 `Settings.dsh: DshSettings`；字段含类型、含义与边界校验，密钥复用用户同步配置。`ChatCapabilities` 由供应商适配器生成，不是部署配置。用户策略为 `models: [{model_id, monthly_token_limit}]`，同一用户可有多个模型，每个模型仅一份配置。一期不配置 RPM、TPM 或并发限流。
- 未发版结构已按用户确认改为 dsh_user_policy 一行一条用户模型授权，取消 model_configs JSON，不新增 Alembic。新安装由 ORM 建表；109 独立联调库单独备份并转换结构，旧镜像必须与新结构配套升级。详见 [单行授权修订](./model-policy-row-revision.md)。
- Gateway 使用现有 `mybatis-plus.db-type`；DM 环境必须设为 `DM`，使席位短事务使用 READ_COMMITTED＋首条 EXCLUSIVE 表锁。锁在提交/回滚时释放；不可仅切换 JDBC URL 却保留 MYSQL 类型。DM 实机本轮暂缓，静态兼容检查不代表部署吞吐量已验证。
- 发布前向客户端同步 [接口文档](./client-api.md) 的逐模型额度修订。模型选择/切换、调用结束、额度拒绝后查询 `GET /api/v1/dsh/usage?model=bisheng:<id>`；无参数只作汇总展示，汇总额度不能决定某个模型可调用。

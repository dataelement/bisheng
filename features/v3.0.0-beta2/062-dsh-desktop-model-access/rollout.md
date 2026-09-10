# F062 部署与回退操作说明

本文交付运行接线，不表示已部署。BiSheng 分支 `feat/3.0.0-beta2-pre`；Gateway 分支 `feat/dsh-access`。执行前使用正式发布制品与本环境自己的 Secret；以下均为配置结构，不含真实凭据。

## 入口与相互信任

客户端只配置一个 HTTP 或 HTTPS Nginx origin。Nginx 的 `/api/*` 进入 Gateway；Gateway 的版本化 `/api/v1/*`、`/api/v2/*` 进入 Python。页面由平台 SPA 提供 `/desktop-login`。DSH 模型流不得经过旧响应包装或整段缓存，Nginx 也应关闭对应 SSE 缓存并允许长连接。

两服务的内部地址使用固定 HTTP/HTTPS origin；HTTPS 仍校验证书。109 联调使用 HTTP，公开地址为 `http://192.168.106.109:13001`，无证书导入要求。仅复用原用户同步的一个共享 Secret，不另配双向 HMAC、Token 公私钥或 issuer；两端派生规则见 [部署配置简化](./deployment-simplification.md)。

| Python 配置 | Gateway 配置 | 约束 |
|---|---|---|
| dsh.installation_id | dsh.installation-id | 同一安装实例 |
| dsh.platform_public_url | dsh.public-origin | 客户端可访问的 Nginx origin |
| dsh.gateway_internal_url | dsh.python-origin | 分别指向对端内部 HTTP/HTTPS origin |
| sso_sync.gateway_hmac_secret | bisheng.gateway-hmac-secret | 现有共享 Secret |
| settings.redis_url | Gateway 原 Redis 配置 | 不新增 DSH Redis 地址 |
| dsh.billing_timezone | — | 默认 Asia/Shanghai |
| — | dsh.license-verification-keys | 既有 License 扩展验证，与 HMAC 分离 |

quota_evidence_bucket、quota_approval_object/sha256 保留为受控账本恢复配置；不在客户端暴露。dsh.enabled 默认关闭。

## 数据与服务启动

1. 备份两个业务库。Gateway 按方言执行 `docker/db/update_dsh_mysql.sql` 或 `update_dsh_dm.sql`，仅新增四张 DSH 表及索引；脚本遇到已有对象会失败，必须先核对已部署 schema，不能通过删表重跑解决。未发布的本次草案投影列由 128 扩为 MySQL 510 字符 / DM8 2040 字节；DM device_label 由 128 扩为 400 字节以容纳 100 Unicode 码点；如果先前手工执行过草案，先只读核对两个姓名字段与索引，再做保留数据的扩列迁移。
2. Python 四张独立表进入既有模型发现/create_all 流程；原 User 表通过正式 `v3_0_0_f062_profile_version` revision 增加版本列。按现有 Alembic 发布流程执行，保留版本链；不重置已有资料版本或配额历史。
3. 复用毕昇既有 Redis 连接配置。当前 DSH 受控连接支持单实例/Sentinel，不支持 Cluster。不要为 DSH 修改共享实例的淘汰策略；首次开通与恢复继续绑定 Redis run_id/epoch/evicted_keys，丢失账本不能按零初始化。
4. 沿用现有 MinIO 和受控恢复审批对象，保留版本、摘要和访问权限；首次配置时核实共享 Redis 历史与待投影事件。
5. 在毕昇模型管理中配置供应商及模型，再通过 DSH 界面配置用户每模型授权和月额度。不再填写模型部署白名单。

6. 部署 `dsh.enabled` 默认 false；部署者开启后，超级管理员进入 DSH 管理页启用业务开关，并保存本组织受控的无凭证 HTTP(S) 下载地址。业务开关默认关闭，旧部署开关为 true 不会自动开启业务。未配置时页面保留联系管理员和手动填写平台地址，不能交付虚构链接。下载包和自定义协议注册由 DSH Desktop 项目提供。

## Gateway License 激活

扩展只追加到旧 License 解密 JSON 的 `dsh_entitlement`，不改变旧 `version/expireDay`。发布含扩展的旧 RSA 外层密文前，必须完成 [发行工具契约](./license-issuer-contract.md) 中的目标旧制品兼容验收；本地新签名向量不能代替厂商样本。

本地运维入口为打包内 `com.dataelem.gateway.dsh.cli.DshActivationCommand`。它只支持 pause/status/resume，不提供伪造副本 ACK、删除席位或强制清空 inflight。操作进程必须拥有本环境共享激活 Redis 的受控访问权限；凭据来自环境/Secret 注入，不放在命令参数。

```sh
# 由 Secret/运行环境提供：DSH_ACTIVATION_REDIS_HOST、PORT、DATABASE。
# 如适用，另提供 USERNAME、PASSWORD、SSL=true；TLS 继续验证证书。
java -Dloader.main=com.dataelem.gateway.dsh.cli.DshActivationCommand \
  -cp gateway-0.0.1-SNAPSHOT.jar org.springframework.boot.loader.launch.PropertiesLauncher \
  pause <installation-id> <signed-license-id> <compact-JWS-SHA256> <replica-a,replica-b>
```

先 pause 目标版本和全部部署副本，再等 inflight 为 0。随后向每个副本安装同一 License，副本自行验证并通过周期观察提交 ACK。`digest` 是 Compact JWS 原始 ASCII 字节的 SHA256，不是外层密文或解密 JSON 的摘要。

```sh
java -Dloader.main=com.dataelem.gateway.dsh.cli.DshActivationCommand \
  -cp gateway-0.0.1-SNAPSHOT.jar org.springframework.boot.loader.launch.PropertiesLauncher \
  status <installation-id>
java -Dloader.main=com.dataelem.gateway.dsh.cli.DshActivationCommand \
  -cp gateway-0.0.1-SNAPSHOT.jar org.springframework.boot.loader.launch.PropertiesLauncher \
  resume <installation-id>
```

status 显示 phase、version、digest、inflight 与 required/ack；未初始化退出码为 2。resume 缺少任一副本确认或尚未排空时退出码为 2，不能把它当成功。副本故障留下的 inflight 需要先确认相关事务结果，再受控修复；不可按超时自动归零。降配不会删除席位，容量已超限时只禁止新分配。

## 配额首次初始化和持续运行

首次无审批时，管理员正常保存一个真实用户的初始策略：系统先持久化操作及禁用的 version 0 占位，因账本未获批准保留 PROCESSING，尚不允许调用。随后按 [配额运维文档](./quota-operations.md) 的 initialize 流程提交该用户的空历史证据与 version 0 manifest，获得不可变审批。向 API 和 Worker 配置相同审批 object/sha256，重新启动后恢复同一操作 ID，使策略完成 0→1。无需手写 SQL，也不能换新操作 ID 绕过处理中状态。

普通后续用户由同一已批准账本上的策略事务自动创建 version 0 gate，再安装目标策略；月份切换由 SQL 空历史和 Redis 永久月份记录共同证明，不会抹去跨月 UNKNOWN。Worker 实际注册 `dsh.project_usage`、`inspect_usage`、`reconcile_usage`、`resume_operation`、`scan_operations`、`scan_profiles`、`scan_usage`；启用时 Beat 派发投影、巡检、操作恢复和资料补偿。保持现有队列与单一 Beat 调度部署纪律。

Redis 连接/主节点身份不再可信时，本进程关闭准入，不能以旧审批自动重连恢复。按证据恢复流程生成新审批并更新全部调用方。SQL 用量降级只用于显示：`persisted` 的 quota_state 固定 unavailable；不能用 SQL 延迟快照继续放行。UNKNOWN 记录缺失用量原因，不冻结用户；若后续补记用量，必须提供逐请求供应商证据，没有“强制解冻”入口。

## 联调与回退

先完成 [客户端交接清单](./desktop-handoff-checklist.md) 中登录、刷新、退出、两个角色范围、流取消和故障场景。查看 DSH request_id 对应的 SQL 明细、Redis 投影积压和 `dsh_settlement` 日志；日志不得记录 Token、完整消息或票据。遥测不是硬账本。

回退时先停止新 DSH 准入，保留已分配席位、会话/refresh 摘要、审计和配额数据，妥善结算在途请求。关闭开关仍保留 Gateway 安装实例标识和原用户同步共享 HMAC Secret，使本版 DSH 凭据可退出；DSH Token 不再配置公钥或私钥。License 验证配置继续独立保留。Python/Worker 停止后不删除 Stream、AOF 或证据。旧商业授权的有效性继续按原字段计算，不因 DSH 关闭延长或缩短。

仍未完成的环境/制品验收以各 acceptance/report 为准。本文不授权发布、生产数据修改或对外发送文档。

## 逐模型配置修订的发布准备（2026-09-09）

- 主配置使用 `Settings.dsh: DshSettings`；字段含类型、含义与边界校验，密钥复用用户同步配置。`ChatCapabilities` 由供应商适配器生成，不是部署配置。用户策略为 `models: [{model_id, monthly_token_limit}]`，同一用户可有多个模型，每个模型仅一份配置。一期不配置 RPM、TPM 或并发限流。
- 未发版结构已按用户确认改为 dsh_user_policy 一行一条用户模型授权，取消 model_configs JSON，不新增 Alembic。新安装由 ORM 建表；109 独立联调库单独备份并转换结构，旧镜像必须与新结构配套升级。详见 [单行授权修订](./model-policy-row-revision.md)。
- Gateway 使用现有 `mybatis-plus.db-type`；DM 环境必须设为 `DM`，使席位短事务使用 READ_COMMITTED＋首条 EXCLUSIVE 表锁。锁在提交/回滚时释放；不可仅切换 JDBC URL 却保留 MYSQL 类型。DM 实机本轮暂缓，静态兼容检查不代表部署吞吐量已验证。
- 发布前向客户端同步 [接口文档](./client-api.md) 的逐模型额度修订。模型选择/切换、调用结束、额度拒绝后查询 `GET /api/v1/dsh/usage?model=bisheng:<id>`；无参数只作汇总展示，汇总额度不能决定某个模型可调用。

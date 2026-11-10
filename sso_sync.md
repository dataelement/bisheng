# sso_sync.md — 企业微信通讯录同步（私有化部署配置指南）

> 适用版本：`release/v3.0.0`（本文 2026-11-09 按当前分支代码核对，未在真实企微租户上联调）
> 相关文档：[网关架构 §8.4 / §10](docs/architecture/11-gateway.md)、[F021 企微 Provider 设计](features/v2.5.1/021-wecom-org-sync-provider/spec.md)、[部署总览](docs/architecture/08-deployment.md)

---

## 0. 结论先看

私有化部署的企微通讯录同步，默认**走商业版 Java 网关的拉取链路**：

```text
企业微信 API ──(weixin-java-cp SDK, 定时)──▶ Gateway ──(HMAC 签名 POST)──▶ BiSheng 后端 ──▶ 部门/用户落库 + org_sync_log
```

- 企微凭据配在**网关**（`custom.wxoauth`），不在 BiSheng 管理台。
- BiSheng 后端只认一个共享密钥：`sso_sync.gateway_hmac_secret`，与网关的 `BISHENG_GATEWAY_HMAC_SECRET` 相同；留空则 fail-closed（拒绝所有推送）。
- **没有网关也可以同步**：用仓库自带的 `scripts/wecom_org_sync.py` 调用同一套 HMAC 接口，见 §8（零后端改动）。

---

## 1. 企业微信后台（客户侧准备）

| 项 | 说明 |
|---|---|
| 企业 ID `corpId` | 我的企业 → 企业信息 |
| 自建应用 `corpSecret` + `agentId` | 应用管理 → 自建应用 → Secret 与 AgentId |
| **通讯录可见范围** | 自建应用的可见范围必须覆盖要同步的部门，否则拉取报 `errcode=60011`（"应用无权限访问通讯录"） |
| 企业可信 IP | 网关所在服务器的出口 IP（自建应用调用接口所需） |
| 预期同步范围 | 只有可见范围内、且启用状态的成员会落库；停用/离职成员在后续对账中被归档 |
| 网络 | 网关容器需能出网访问 `qyapi.weixin.qq.com:443`；有出网白名单/代理的环境需放行 |

---

## 2. 网关配置（商业版，`gateway` profile）

### 2.1 启用网关

```bash
bash docker/install.sh --gateway \
  --license-file /secure/path/license.txt \
  --public-url http://服务器IP:3001
```

install.sh 会写 `docker/.env`（license、HMAC 密钥、网关库密码）并切到 `gateway` profile。没有 license 文件则不启用网关。

### 2.2 打开同步开关

`docker/gateway/config/application.yml`：

```yaml
bisheng:
  enable-sync: false   # ← 改为 true 才执行企微通讯录同步（架构文档里写作 enable_sync，等价）
  time: 1              # 每天几点执行，0~23；cron 为 `0 0 <time> * * ?`
```

改完需要**重启网关容器**（`docker compose restart gateway`）——该文件是只读挂载，Spring 只在启动时读取。

### 2.3 企微凭据

同一文件中的 `custom.wxoauth`（SSO 扫码/网页登录与通讯录同步共用这份凭据）：

```yaml
custom:
  wxoauth:
    clientId: <corpId>
    clientSecret: <corpSecret>
    agentId: <agentId>
    redirectUri: http://gateway-host/api/wx/callback
    redirectWebUri: https://domain/oauth/api/wxweb/callback?flowId=flow_id
    userName: name            # name 或 userid
```

### 2.4 环境变量（`docker/.env`）

| 变量 | 说明 |
|---|---|
| `BISHENG_GATEWAY_LICENSE` / `BISHENG_GATEWAY_LICENSE_FILE` | 网关 license |
| `BISHENG_GATEWAY_HMAC_SECRET` | 与后端共享的签名密钥；**足够长的随机串**，不得沿用示例值，也不得跨环境复用 |
| `BISHENG_PUBLIC_URL` | 平台对外地址 |
| `BISHENG_GATEWAY_DB_PASSWORD` | 网关独立库 `bisheng_gateway` 的密码 |

---

## 3. BiSheng 后端配置

```yaml
# src/backend/bisheng/config.yaml:54
sso_sync:
  gateway_hmac_secret: ""        # 必须等于网关的 BISHENG_GATEWAY_HMAC_SECRET
  signature_header: "X-Signature"
```

- **留空 = fail-closed**：`/internal/sso/login-sync`、`/internal/sso/gateway-wecom-org-sync`、`/departments/sync`、`/internal/departments/relink*` 全部拒绝。
- 该配置**不读取 `BS_*` 环境变量**（plain BaseModel，只从 `config.yaml` 或其 `!env` 标签取值）。
- **docker 部署无需手工同步密钥**：`docker/bisheng/config/config.yaml:55` 已是 `gateway_hmac_secret: !env ${BISHENG_GATEWAY_HMAC_SECRET}`，与网关读同一个 `.env` 值。
- 签名算法：`SHA256(METHOD + "\n" + PATH + "\n" + raw_body)`，hex 小写，放在 `X-Signature` 头。
- `orphan_config_id`（默认 9999）：F014 迁移预置的 `org_sync_config` 行，用于承接网关推送产生的日志，无需人工创建。

---

## 4. 数据流与落库

1. 网关 `WechatScheduled` 按 `bisheng.time` 触发，用 `weixin-java-cp` 4.7.0 拉取完整部门树 + 成员列表。
2. 网关调用 `POST /api/v1/internal/sso/gateway-wecom-org-sync`（HMAC 校验），payload = `departments` + `members`。
3. 后端 `DepartmentsSyncService` 做部门 upsert/归档，`LoginSyncService` 逐个处理成员（创建/合并/禁用），最后汇总**一条** `org_sync_log`。
4. 批量推送时以 `full_snapshot` 标记最后一批权威快照，缺席归档只在该批触发——分批推送不会误删数据。
5. 落库字段：新增用户 `source='wecom'`、`external_id=<企微 userid>`；本地同名邮箱用户按规则合并而非重复创建。
6. **管理台手动触发**（系统管理 → 组织同步 → 「立即同步」）：`POST /api/v1/org-sync/execute`（body `{"config_id": N}`）→ Celery 任务 `bisheng.worker.org_sync.tasks.execute_org_sync` → 用 `WeComProvider` 拉取后走**同一个** `apply_wecom_org_snapshot`，日志记 `trigger_type='manual'`、`config_id=<配置 id>`。任务在 Celery 默认队列（`celery`）执行，生产由 entrypoint 启动的 worker 消费，本地需 `make worker-default`。
7. **初始密码（可选，`sso_sync.initial_password`）**：非空时，同步只给**空密码**的同步用户补 `md5(initial_password)`——用户/管理员已经设置过的密码永不覆盖。仍在使用该密码的账号登录会返回 **10601**，平台登录页自动跳到改密页（输入当前初始密码 + 新密码），改完即可正常登录。建议只在初次导入/上线窗口开启，之后把配置改回留空（已改密的用户不受影响）；注意它是**共享密码**，只应配合强制改密使用。
   - docker 部署：`docker/bisheng/config/config.yaml` 的 `sso_sync.initial_password`（默认 `""` = 关闭）。
   - 源码部署：`src/backend/bisheng/config.yaml`。
8. **失败也有记录**：任一环节抛异常时，服务会写一条 `status='failed'` 的 `org_sync_log`（`error_details` 带异常摘要）再把异常抛给调用方，页面/排障能看到这次尝试，而不是静默无记录。
9. **防重复提交（三层）**：① 页面在 `sync_status=running` 时禁用按钮、请求在飞行中也不可再点；② API 入队前取 Redis NX 锁 `org_sync:enqueue:{config_id}`（TTL 30 分钟，任务 `finally` 释放），重复点击/并发管理员直接返回 22003，不会多排一条任务；③ 任务内 `sync_status` CAS（`idle→running`）兜底，即使锁过期也不会并发执行。Redis 不可用时锁降级为放行，由第 ③ 层保证不并发。

---

## 5. 多租户

- 单租户部署：无需任何额外配置，部门与成员都归根租户。
- 多租户：部门 → 子租户的挂载由推送里的 `tenant_mapping` 自动完成，只允许两级租户树；已挂载的部门（`is_tenant_root=1`）以 BiSheng 侧状态为准，不被上游覆盖。

---

## 6. 验收与排障

| 检查点 | 方法 |
|---|---|
| 网关是否启用了同步 | 网关日志；`docker/gateway/config/application.yml` 的 `enable-sync` 是否为 `true` |
| 推送是否到达后端 | 平台 → 系统管理 → **组织同步**（超管可见）查看日志；对应 `org_sync_log` 表。触发方式区分：网关推送=`sso_realtime`、脚本/定时=`scheduled`、管理台手动=`manual` |
| 401 / 无日志 | 两侧 HMAC 密钥不一致，或后端 `gateway_hmac_secret` 仍为空（fail-closed） |
| 拉不到通讯录 | 企微应用可见范围未覆盖目标部门（`errcode=60011`）、可信 IP 未配置、网关出网被拦 |
| 部门/人员被误归档 | 检查 `full_snapshot` 语义：只有权威快照批次才触发缺席归档 |
| 「立即同步」点了没反应 | 任务走 Celery 默认队列：生产确认 entrypoint 启动的 worker 在线，本地 `make worker-default`；`org_sync_log` 出现 `trigger_type='manual'` 即已执行 |

---

## 7. ⚠️ 已知限制：无网关时的原生同步不可用

仓库里保留了后端原生组织同步的**配置 CRUD**（`org_sync_config` 表、`provider=wecom`、管理台表单字段 `corpid/corpsecret/agent_id/allow_dept_ids`），但**执行器已被删除**：

- commit `d351126d1 chore：remove unused code`（2026-06-01，在当前 `release/v3.0.0` 历史中）删除了：
  - `bisheng/org_sync/api/endpoints/sync_exec.py`（测试连接 / 手动同步 / 日志 / 远程树 4 个端点）
  - `bisheng/org_sync/domain/services/org_sync_service.py`（同步执行器）
  - `bisheng/worker/org_sync/tasks.py`（Celery 任务）
- 现状：`/api/v1/org-sync/configs` 只剩增删改查；`OrgReconcileService` 无实例化点，Celery beat 也没有 org sync 任务——当年「管理台点一下同步」和管理台配置页都不存在了。

**因此：没有商业网关时，不能用「管理台配置 + 定时拉取」这套原生链路。** 替代做法见 §8：复用同一套 HMAC 推送接口，零后端改动。

---

## 8. 无网关方案：自建同步器（仓库已提供脚本）

没买/没部署商业版网关的私有化环境，用 `src/backend/scripts/wecom_org_sync.py` 完成同样的事：

```text
企业微信 API ──(WeComProvider, token 缓存/限流复用)──▶ wecom_org_sync.py ──(HMAC POST)──▶ /api/v1/internal/sso/gateway-wecom-org-sync
```

它不引入第二套写入逻辑：落库仍然走 F014 的 `DepartmentsSyncService` / `LoginSyncService`（§4），只是把「拉取」这一段从网关挪到了脚本里。

### 8.1 前提

- 后端 `sso_sync.gateway_hmac_secret` 必须设置（为空时推送一律 19301）。
- 运行环境能访问 `qyapi.weixin.qq.com:443`，并能访问后端 `:7860`。
- 企微凭据二选一：
  - 参数 / 环境变量：`--corpid --corpsecret --agent-id`（或 `WECOM_CORP_ID` / `WECOM_CORP_SECRET` / `WECOM_AGENT_ID`）；
  - 或管理端建一条 `org_sync_config`（`POST /api/v1/org-sync/configs`，`provider=wecom`，`status=active`），脚本自动读取并解密。

### 8.2 运行

```bash
# 源码部署：在 src/backend 下
export config=config.yaml
python scripts/wecom_org_sync.py              # 默认 dry-run：只拉取 + 报告
python scripts/wecom_org_sync.py --apply      # 真正推送

# 容器部署（脚本已随镜像发布到 /app/scripts/）
docker compose exec -T backend python scripts/wecom_org_sync.py --apply

# 本地 make（仓库根目录）
make wecom-sync          # dry-run
make wecom-sync-apply    # 推送
```

常用参数：`--batch-size N`（成员分批，最后一批仍带全量名册并置 `full_snapshot=true`）、`--incremental`（永不 `full_snapshot`，只 upsert，不归档不禁用）、`--allow-dept-ids`（同步根部门，默认 `[1]` 全公司）、`--tenant-id`（读配置的租户）。

退出码：`0` 成功、`1` 部分成员/部门失败、`3` 缺凭据或密钥、`4` 传输或接口失败。

### 8.3 定时执行

```bash
# cron（每天 2:15）
15 2 * * * cd /opt/bisheng/src/backend && config=config.yaml \
    .venv/bin/python scripts/wecom_org_sync.py --apply >> /var/log/bisheng-wecom-sync.log 2>&1

# systemd timer（容器部署示例 ExecStart）
docker compose exec -T backend python scripts/wecom_org_sync.py --apply
```

`--apply` 默认按权威快照执行：上游已删除的部门会被归档、不在名单里的 `source=wecom` 用户会被禁用并强退。周期性执行前建议先跑一次 dry-run 核对规模。脚本推送在 `org_sync_log` 里记为 `trigger_type='scheduled'`，与网关推送（`sso_realtime`）和管理台手动（`manual`）区分开。

### 8.4 已知边界

- **部门负责人（已支持）**：`is_leader_in_dept` 与 `department` 按位对齐，脚本发送 `department_admin_external_ids`；后端只对账 `grant_source='sso'` 的部门管理员授权，管理端手工授权（`manual`）不受影响。上游取消负责人后，下次同步自动回收。
- **多租户挂载**：脚本不发送 `tenant_mapping`；多租户环境需要自动挂载子租户时，要么改用网关，要么在脚本里补充该字段。
- **密钥等同登录态**：拿到后台 HMAC 密钥就能调用 `login-sync` 签发任意用户 JWT，运行脚本的机器必须是受控内网主机。
- **时区**：`org_sync_log` 的起止时间由应用进程的本地时钟生成，需要与数据库时区一致（本仓库容器默认 `TZ=Asia/Shanghai`）。若把后端进程改成 UTC 而数据库保持本地时区，起止时间会再次错位。

---

## 9. 代码锚点

| 内容 | 位置 |
|---|---|
| 后端 SSO 同步配置 | `src/backend/bisheng/config.yaml:54`、`src/backend/bisheng/core/config/sso_sync.py` |
| 容器内后端配置（含 `!env` 注入） | `docker/bisheng/config/config.yaml:54` |
| 网关开关与时间 | `docker/gateway/config/application.yml:60` |
| 网关 env 注入 | `docker/docker-compose.yml`（`gateway` 服务） |
| 企微推送入口 | `src/backend/bisheng/sso_sync/api/endpoints/gateway_wecom_org_sync.py:65` |
| 推送 payload 结构 | `src/backend/bisheng/sso_sync/domain/schemas/payloads.py:220` |
| 租户挂载 | `src/backend/bisheng/sso_sync/domain/services/tenant_mapping_handler.py` |
| 网关设计说明 | `docs/architecture/11-gateway.md` §8.4、§10.2–10.3 |
| 企微 Provider（无网关脚本使用） | `src/backend/bisheng/org_sync/domain/providers/wecom.py` |
| 无网关同步脚本 | `src/backend/scripts/wecom_org_sync.py`（`make wecom-sync` / `wecom-sync-apply`） |
| 脚本单测 | `src/backend/test/org_sync/test_wecom_org_sync_script.py` |

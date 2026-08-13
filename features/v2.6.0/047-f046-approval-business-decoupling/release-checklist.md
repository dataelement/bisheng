# F047 停服发布与恢复演练清单

**适用范围**：从线上 exact `v2.6.0` 停服升级到包含 F045/F046/F047 的同一构建。

**权威口径**：[v2.6.0 release contract](../release-contract.md) 与 [F047 design §13](./design.md#13-发布与回滚)。

**基线提交**：`v2.6.0^{commit}=779d8fb87a1125744af065a21e032c2573167f91`。

> 本清单只适用于 F045/F046 生产零存量。任一零存量门禁不满足，立即停止标准发布，不清理生产数据、不清空 broker、不临时增加兼容 adapter；返回设计评审确认迁移方案。

## 1. 发布原则与角色

- [ ] 发布负责人、DBA、平台运维、业务验收人和回滚决策人均已到场，记录维护窗口与沟通渠道。
- [ ] 已记录目标构建 Git SHA、API/worker/Beat 镜像 digest、配置版本和数据库备份标识；所有进程使用同一目标构建。
- [ ] 已确认本次是完全停服发布：不滚动升级，不允许新旧 API/worker/Beat 并存。
- [ ] 已确认不提供旧 F045/F046 task 名、Deferred token、outbox、Gate/runtime handler adapter，不做双读、双写或开发数据 backfill。
- [ ] 已确认三个已上线场景 `menu_access_request`、`channel_subscribe_request`、`knowledge_space_subscribe_request` 继续使用既有 `approval_outbox` 与默认队列；不得清理或改写其数据。

## 2. 维护窗口前核对

### 2.1 exact `v2.6.0` 基线

- [ ] 在受控发布源执行以下只读命令，并把输出附到发布记录：

```bash
git rev-parse 'refs/tags/v2.6.0^{commit}'
git show --no-patch --format='%H %D' v2.6.0
```

预期 commit 为 `779d8fb87a1125744af065a21e032c2573167f91`。线上每个 API、worker、Beat 实例还必须通过部署平台的只读 inspect 核对镜像 digest 与构建 SHA；`/api/v1/env` 的硬编码版本字段不能作为证据。

- [ ] 线上数据库 Alembic revision 与 exact `v2.6.0` 构建一致，预期为 `f048_merge_f046_f047_heads`；目标构建在演练环境执行 `alembic heads` 只有一个 head：`f046_ks_file_change_approval`。
- [ ] 已完成数据库全量快照/备份和恢复校验，并记录恢复点；只记录备份标识，不把连接串、口令或 token 写入本文档。

### 2.2 停服前排空

- [ ] 先关闭外部流量入口和定时触发入口，等待在途 API 请求结束。
- [ ] 在 worker 仍运行时，用 Celery/部署平台只读 inspect 确认 default `celery`、`knowledge_celery` 以及同一 worker app 的其他队列没有 active/reserved/scheduled 任务。
- [ ] broker 中 default 与 Knowledge 队列的所有 priority shard、unacked/visibility 集合均为零。禁止用 purge、`FLUSHDB`、宽范围 `DEL` 或未经确认的 `KEYS *` 把非零伪造成零。

若任一队列非零，继续由旧版本 worker 排空并重新检查；无法判定消息归属或无法排空时，阻断发布。

## 3. 完全停服与零存量门禁

### 3.1 停止顺序

- [ ] 停 API。
- [ ] 停 Beat，确认没有新的周期任务入队。
- [ ] 停 default Celery worker。
- [ ] 停 `knowledge_celery` worker；同一发布单元内的其他 Celery worker也一并停止，避免旧代码继续导入或发送任务。
- [ ] 通过进程、容器和 Celery inspect 三类只读证据确认所有旧 API/worker/Beat 已退出；不要只看编排平台的期望副本数。
- [ ] 再次核对 broker 队列、priority shard 与 unacked/visibility 集合为零。

### 3.2 数据库只读门禁

下列 SQL 只允许使用只读账号执行。两个场景的正式 code 是：

```text
resource_user_invite_confirmation
knowledge_space_file_change_request
```

- [ ] `approval_scenario` 两个 code 均为零：

```sql
SELECT scenario_code, COUNT(*) AS row_count
FROM approval_scenario
WHERE scenario_code IN (
  'resource_user_invite_confirmation',
  'knowledge_space_file_change_request'
)
GROUP BY scenario_code;
```

- [ ] `approval_instance` 两个 code 均为零：

```sql
SELECT scenario_code, COUNT(*) AS row_count
FROM approval_instance
WHERE scenario_code IN (
  'resource_user_invite_confirmation',
  'knowledge_space_file_change_request'
)
GROUP BY scenario_code;
```

- [ ] 若下列未发布表不存在，记录 `ABSENT`；若存在，则每张表必须为零。表存在性由 DBA 使用当前数据库方言的系统目录只读查询确认，不把“查询报表不存在”当作脚本成功：

```sql
SELECT COUNT(*) AS row_count FROM approval_decision_outbox;
SELECT COUNT(*) AS row_count FROM resource_user_invite_request;
SELECT COUNT(*) AS row_count FROM knowledge_space_file_change_policy;
SELECT COUNT(*) AS row_count FROM knowledge_space_file_change_setting;
SELECT COUNT(*) AS row_count FROM knowledge_space_file_change_request;
SELECT COUNT(*) AS row_count FROM knowledge_space_upload_stage;
SELECT COUNT(*) AS row_count FROM knowledge_space_file_change_footprint;
SELECT COUNT(*) AS row_count FROM knowledge_space_file_change_execution_step;
```

- [ ] 对已有 `approval_outbox` 做交叉检查，两个新场景不得有 legacy outbox：

```sql
SELECT ai.scenario_code, COUNT(*) AS row_count
FROM approval_outbox ao
JOIN approval_instance ai ON ai.id = ao.instance_id
WHERE ai.scenario_code IN (
  'resource_user_invite_confirmation',
  'knowledge_space_file_change_request'
)
GROUP BY ai.scenario_code;
```

- [ ] broker 对以下旧 F046 任务名前缀及旧消息 payload 检查为零：`bisheng.worker.approval.file_change_tasks.*`。default 队列整体已排空，因此旧 F045 复用的 generic approval-outbox 消息也不可能残留。

**阻断判定**：以上任意查询返回非零、表存在性无法判定、broker 消息无法反序列化确认、旧进程未完全退出，均阻断标准发布。不得在生产现场删除记录、丢弃消息或编写一次性兼容代码绕过门禁。

## 4. 迁移与部署顺序

- [ ] 复核数据库恢复点仍可用，并记录停服后的最终数据时间点。
- [ ] 拉取目标构建但保持 API/worker/Beat 全部停止；再次核对目标 Git SHA 与所有镜像 digest 一致。
- [ ] 只使用目标构建执行迁移预检：

```bash
cd src/backend
.venv/bin/alembic heads
.venv/bin/alembic history -r f048_merge_f046_f047_heads:f046_ks_file_change_approval
```

预期唯一 head 为 `f046_ks_file_change_approval`，且它直接位于线上 `f048_merge_f046_f047_heads` 之后。

- [ ] DBA 在目标构建中执行 `alembic upgrade head`；不得使用旧 `v2.6.0` 镜像执行新 revision。
- [ ] 升级后只读执行 `alembic current`，确认当前 revision 为 `f046_ks_file_change_approval (head)`。
- [ ] 只读核对本 revision 的八张新表均存在：

```text
approval_decision_outbox
resource_user_invite_request
knowledge_space_file_change_policy
knowledge_space_file_change_setting
knowledge_space_upload_stage
knowledge_space_file_change_request
knowledge_space_file_change_footprint
knowledge_space_file_change_execution_step
```

- [ ] 复核 `approval_outbox` 既有三场景数据、索引和状态未被清理或重写；迁移不执行生产数据 backfill。

## 5. 启动顺序与注册门禁

- [ ] 先启动目标版本 default worker，确认启动期 `bootstrap_approval_scenarios()` 成功，F045/F046 policy/subscriber 协议与 event version 完整注册；缺失或不匹配必须启动失败，不能降级。
- [ ] 启动目标版本 `knowledge_celery` worker，确认其 active queue 只有预期 Knowledge 路由，并注册 `bisheng.worker.knowledge.file_change_tasks.*`。
- [ ] 若还有同发布单元 worker，全部升级到同一镜像 digest 后再启动；确认不存在旧 worker 节点。
- [ ] 通过 Celery inspect 核对 default worker注册 decision delivery 与 Permission task，Knowledge worker注册 F046 task；同时核对 active queues，不能只看进程存活。
- [ ] 启动 API，确认健康检查和场景 bootstrap 通过。
- [ ] 最后启动 Beat，确认四个 F046 周期任务字符串均指向 `bisheng.worker.knowledge.file_change_tasks.*` 并路由 `knowledge_celery`。
- [ ] 恢复外部流量前，确认新旧进程数量、构建 SHA、镜像 digest、队列路由和 Alembic head 已记录且一致。

## 6. Smoke 验证

所有 smoke 使用专用租户和可追踪前缀；每一步以数据库/业务 API 的最终事实为准，HTTP 200、toast、broker task ID 或 ACK 不能单独证明完成。

### 6.1 默认队列与 legacy 回归

- [ ] 对菜单、频道订阅或知识空间加入任选一个已上线场景走到 pass/最后节点。
- [ ] 预期只创建 `approval_outbox`，不创建 `approval_decision_outbox`；default worker执行原 handler，outbox 成功且 instance 进入既有 executed 终态。

### 6.2 F045 decision delivery 与 Permission worker

- [ ] 创建一条个人用户邀请，确认 Permission `resource_user_invite_request=awaiting_approval` 与 Approval instance/task 原子绑定，且没有 `approval_outbox`。
- [ ] 被邀请用户本人 approve；确认 Approval instance 保持 `approved`，同事务仅生成唯一 `approval_decision_outbox`。
- [ ] 确认 default decision-delivery worker把事件交给 Permission subscriber，事件为 `delivered`；Permission request 经 `queued/applying` 到 `applied`，资源 owner 权威授权可见。
- [ ] 确认业务执行期间和完成后不产生 Approval `executing/executed/execute_failed`，也不产生 `execute_failed` exception。

### 6.3 F046 decision delivery 与 Knowledge worker

- [ ] 创建一条可回收的文件变更申请，确认 Knowledge request/stage/footprint 与 Approval instance/task 同提交，业务 API 显示 `queued + approval_status=pending`，且没有 `approval_outbox`。
- [ ] 当前有效 owner/manager approve；确认唯一 decision event由 default worker交付，Knowledge request先提交 `queued`，再由 `knowledge_celery` 推进 `applying/applied`。
- [ ] 对 upload 验证正式文件图、FGA 权限与普通解析调度均已接受后才解除发布门禁；审批中心始终只显示审批终态。
- [ ] 验证至少一次同 event 重复投递或同 request 协调不会重复业务副作用；stale Knowledge execution token 不改变当前 generation，且系统中不存在 legacy Approval Deferred token/task adapter。

### 6.4 Smoke 通过条件

- [ ] default queue、`knowledge_celery`、decision outbox 与两个业务 request 均收敛，无 permanent failure、未知 task、路由错误或持续重试。
- [ ] 三个 legacy 场景继续走 `ApprovalOutbox`；F045/F046 只走 `ApprovalDecisionOutbox`。
- [ ] API、default worker、Knowledge worker、Beat 日志均无 registry/version/tenant ContextVar 错误，且未记录秘密 payload、token 或内部对象地址。

## 7. 回滚与恢复演练

### 7.1 可以直接回退到 exact `v2.6.0` 的条件

只有以下条件全部满足，才可走标准应用/DDL 回退：

- API/Beat/全部 worker再次完全停止，broker 相关队列与 unacked 均为零。
- 两个 scenario、instance、decision outbox、Permission request、Knowledge policy/setting/request/stage/footprint/step 均为零或未创建。
- 尚未对 F045/F046 产生任何需保留的业务副作用。
- 三个 legacy 场景的 `approval_outbox` 数据完整且无需回退。

满足条件时，使用目标构建的 migration 执行：

```bash
cd src/backend
.venv/bin/alembic downgrade f048_merge_f046_f047_heads
```

该 downgrade 只允许删除本次 revision 创建的八张新表；不得 drop/alter `approval_instance`、`approval_task`、`approval_exception`、`approval_outbox`、`approval_action_log`，不得删除三个 legacy 场景数据。确认 Alembic current回到 `f048_merge_f046_f047_heads` 后，部署 exact `v2.6.0` 的同一镜像 digest，并仍按“worker → API → Beat”整组启动。

### 7.2 禁止直接降级的条件

出现以下任一情况，不得直接降回不认识 F045/F046 的 `v2.6.0`：

- 已创建任一 F045/F046 scenario、instance、decision event 或业务 request。
- 已产生 Permission 授权、Knowledge 正式文件、FGA/MinIO/ES/Milvus 副作用或待补偿 step。
- broker 中仍有 decision、Permission 或 Knowledge task，或存在无法判定归属的消息。
- migration 部分完成、表/索引状态不确定，或数据库快照不可验证恢复。

此时保持停服，关闭两个新场景入口，保留数据库与 broker现场；由回滚决策人选择：

1. 修复后前滚同一架构，完成或补偿业务；或
2. 恢复发布前**完整数据库快照**并同步恢复受影响的外部业务状态，再部署 exact `v2.6.0`。

broker 不是事实源，不能用删除消息代替恢复；恢复以 Approval decision outbox、Permission/Knowledge request、step/footprint 与资源 owner权威状态为准。

### 7.3 回滚触发条件

- policy/subscriber registry 无法完整启动或协议版本不一致。
- Alembic 未到唯一目标 head，或八张新表/索引与目标模型不一致。
- default/Knowledge task 路由错误、出现未知旧 task，或发现新旧 worker混跑。
- decision delivery 出现持续 permanent failure，或 F045/F046 发生跨 tenant、重复副作用、审批终态被业务失败回写。
- F046 发布门禁提前解除、权威完成判据失效或补偿无法收敛。

## 8. 演练记录

| 项目 | 证据/输出 | 执行人 | 时间 | 结果 |
|---|---|---|---|---|
| exact `v2.6.0` SHA 与线上镜像 digest |  |  |  |  |
| DB/外部存储恢复点 |  |  |  |  |
| 停服与旧进程清零 |  |  |  |  |
| F045/F046 数据零存量门禁 |  |  |  |  |
| broker 队列/priority/unacked 清零 |  |  |  |  |
| Alembic upgrade/current/head |  |  |  |  |
| worker registry 与 active queues |  |  |  |  |
| legacy default smoke |  |  |  |  |
| F045 decision/default smoke |  |  |  |  |
| F046 decision/knowledge smoke |  |  |  |  |
| 回滚条件判定或恢复演练 |  |  |  |  |

**最终结论**：仅当零存量门禁、迁移、整组同版本启动和三组 smoke 全部有证据通过，才允许结束维护窗口。任何“先上线再观察”“临时保留旧 worker”“先兼容旧消息”的做法都不属于本发布方案。

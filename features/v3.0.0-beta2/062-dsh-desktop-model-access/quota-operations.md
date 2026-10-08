# DSH 额度运行与自动恢复

2026-09-11：本页替代旧 MinIO 证据、人工 initialize/recover/reconcile 和确认对象流程。用户已确认接受 SQL 异步尾部缺口，详见 [SQL 自动恢复修订](./sql-quota-recovery-revision.md)。

## 正常记账

调用开始和结算写 Redis Stream；Worker 默认每 5 秒扫描一次，按用户每批最多 500 条投影到 SQL。明细与月汇总同事务提交后才 ACK，事件重放不重复累计。实际延迟是扫描等待加队列等待及数据库耗时；5 秒不是延迟保证。默认超过 30 秒积压或达到高水位会暂停新调用，这同样不是丢失窗口上界。

## 部署

删除 `dsh.quota_evidence_bucket`、`dsh.quota_approval_object`、`dsh.quota_approval_sha256`。无需 DSH 专用 MinIO 桶、版本对象或人工批准 Redis 运行标识。正常保存每个用户/模型额度即可初始化。不要删除 SQL 策略、明细或汇总；历史 MinIO 材料不由应用清理。

## Redis 故障

Redis 不可用时调用失败；恢复连接后自动处理。完整账本保留；缺失账本从 SQL 已落库明细/汇总重建，同时合并尚存 Redis 请求的较新版本并保留已有用量。只在 SQL 存在的 RUNNING 请求标记 USAGE_UNKNOWN，不能猜测 Token 数。完全未落库且无法找回的事件会丢失；这不是无损恢复。

恢复按用户加共享 30 秒租约，逐批续租与校验所有者。旧恢复者不能覆盖新恢复者；同一用户恢复期间暂不可调用，其他用户不因该租约停用。SQL 查询失败或策略发生并发变化时保持不可用并等待重试，不按空账本放行。恢复清单在内存保存全部用户历史，Redis 每批最多 100 个请求写入，实际内存/耗时随历史量增长。

## 运维观察

检查 Worker/Beat 是否运行、Stream 积压及日志中的 `DSH Redis ledger recovered`；仍出现恢复错误时先检查 SQL/Redis 可用性和策略一致性。正常未知用量不冻结用户。不再提供人工补记或强制恢复命令；保留原有审计历史。

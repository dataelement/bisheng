# Retrospective: 发布申请提交性能优化（第一阶段）

**Feature ID**: `054-file-publish-submit-performance`  
**Date**: 2026-07-14

## 1. 结果

第一阶段按已确认范围落地：提交目标复验由目标空间全量扫描改为按 ID 定向读取；移除目标文件 `view_file`；发布初始提醒改为独立通知 outbox + Celery + 30 秒 Beat 补偿；首节点审批任务改为单事务批量写入；提交路径新增分段耗时日志。API 请求、响应和审批状态语义保持不变。

当前只证明结构性耗时项已从同步链路移除或降为常数级查询，尚未在生产同等数据规模上量化 14 秒降低到多少。

## 2. 有效做法

- 先用专项测试锁定“不再全量搜索、不再调用 `view_file`、响应结构不变”，使性能优化不改变权限和 API 边界。
- 通知使用独立 outbox，避免复用业务执行 `ApprovalOutbox` 后错误推进审批实例状态。
- 保留原通知 Service 的静态接口，只为文件发布增加 outbox 编排，减少对其他审批消息场景的影响。
- 先建立分段日志，再判断第二阶段是否需要优化 OpenFGA 审批人解析，避免无证据扩大改动。

## 3. 偏差与原因

- 设计表述使用了 `Transactional Outbox`，实际实现中审批事实与通知 outbox 未共享同一事务，因为现有 `ApprovalGate` 内部独立提交实例和任务。要做到原子提交需要重构 Gate/Repository 的事务边界，超出已确认第一阶段范围。
- 知识版本服务的既有 SQLite fixture 与当前 `KnowledgeFile` schema 漂移，定向目标测试改用 Repository mock，未顺带修改公共 fixture。
- 审批目录存在 15 个既有失败；本次使用专项回归证明改动链路，并保留全量失败证据，没有为追求全绿而修改无关业务。

## 4. 风险与后续建议

1. 第二阶段优先基于生产分段日志评估 `base_validation_ms` 与 `approval_create_ms`，确认 OpenFGA owner/manager 查询是否仍是主耗时。
2. 若业务要求“审批事实与通知意图绝不丢失”，应单独立项统一审批事务边界，或增加按 pending 实例反查缺失通知 outbox 的补偿任务。
3. 上线前必须在 MySQL/DM8 验证 F058 升降级，并联调 Worker、Beat、Redis 锁和消息中心。
4. 对消息接收方可增加业务幂等键，进一步降低 at-least-once 造成重复提醒的可见影响。

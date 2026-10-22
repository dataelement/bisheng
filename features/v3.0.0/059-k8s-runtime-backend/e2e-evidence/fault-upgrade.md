# F059 故障与升级验收（进行中）

## 109 真实 prepare 取消

固定 runtime 源码 `54b3ea2c1`，专用测试平台与 Node profile revision=1。`e2e-f059-cancel-d109c2` 的真实 npm 根 postinstall 已打印固定 BEGIN 标记；按精确 app/deployment/kind=prepare 查询账本，120 秒内获取仍 running/preparing 的绑定后调用 owner 取消接口。

| 检查 | 实际结果 |
| --- | --- |
| owner cancel / 非 owner、跨租户 cancel | 成功 / 两者精确 16105 |
| 操作终态 | cancelled / operation_cancelled / cleanup complete |
| 发布结果 | 预检失败、无审批和正式版本 |
| 运行写入者清理 | 同一实际 CID 连续两次不存在，剩余该操作容器为 0 |
| 人工强制清理 | 未执行 |

应用、部署、版本、操作和实际 CID 及四份脱敏证据摘要见 [JSON](./fault-upgrade.json)。先前 d109c1 误用 revision=2 被拒绝，保留 setup 失败记录，不能计为取消验证。

## 未完成项

189 初始化失败、取消、未知写入者、响应丢失、manager 重启、迁移失败/快照恢复、升级/卸载保留和最终清理尚未完成。私有故障代理与夹具本地测试只证明工具行为。单节点结果不能代表 NodeLost 跨节点围栏；T070 保持 pending。

## 109 实际迁移基线（尚未v2/恢复）

v1实际发布、独立审批12 executed，generation1/deploy completed与cleanup complete后，owner两次PATCH写入随机哨兵与NULL。每次写前非owner16162、跨租户16101且rows未变；两行及其SHA/随机值SHA已冻结于私有0600证据，完整ID见JSON。旧测试工具误把终态写成approved，曾在任何数据写前拒绝；修正后只对原成功发布接续两行PATCH，没有重复发布。v2失败和恢复仍待执行，不能把准备或本地SQLite repro计为平台故障通过。

189新r2先准备未到创建资源阶段，controller空闲租约已过期导致renew409与terminal fact失败；前端部署最终16227/operation_timeout，但manager op仍running/admitted/cleanup pending。未修改租约、无Pod/PVC；登记T198/T199后正常修复。旧r2 journal与失败记录保留，不原地抹去重跑。

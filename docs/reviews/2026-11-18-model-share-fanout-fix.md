# 新子租户模型共享下发修复

## 范围

基于远端 `feat/3.1.0-beta1` 最新 `4115aaca41c78391e09c7766eb848f1fb355ad26`，分支 `codex/3.1.0-beta1/model-share-fanout-fix-20261118`。使用独立工作区，先前元数据修复提交 `253f35a36d` 保留在原分支，本分支不夹带该提交。主工作区未修改。

这是恢复原有行为的 hotfix：不增加 API/数据库结构或授权协议。116 本轮仍只读，没有部署、更新计划、清除锁或补写共享关系。

## 116 根因证据

1. Root 提供商 358（阿里云百炼 测试每日调用次数）实际只共享给 19、20、25、26、28、60、65。67、68、69、70 无对应 shared_with；四个租户的创建日志均记录模型 fanout 的字符串格式化异常。
2. 以租户 69 为例，原 trace `591c1eb494214e45ad186aa9cc1f39d6` 在 2026-11-18 11:47:17.370947 记录 `The operation impact has changed; review and confirm it again`，随后记录 `not all arguments converted during string formatting`。
3. Root 提供商查询第一个 ID 为 12。该提供商存在旧 PREPARING 计划 `e8e882d2-fa74-49d2-b38a-388d350b791d`（创建于 2026-11-13，actor_user_id=3），其 request_hash 正确、plan_digest 校验失败。将读取副本的 expires_at 减一秒后摘要匹配；这只是内存诊断，未更新数据库。
4. 全部 81 条 model_share_server 计划中有 45 条呈相同特征：request_hash 正确、expiry 摘要不匹配，向前一秒可精确匹配原 plan_digest；其中 44 条已 COMPLETED，1 条 PREPARING。不能因此把这些历史记录全部标为成功或删除。
5. 实际 MySQL 只读 CAST 证实：`00:00:00.499999` 存为 `00:00:00`，`.500000`、`.999999` 均舍入为 `00:00:01`。表列为 DATETIME(0)。共享计划创建使用未归一化 clock；摘要却按 `_utc()` 截到整秒，跨存储读取时可能差一秒。普通模型删除确认已经提前做了该归一化，共享预留分支遗漏。
6. 首个提供商被旧计划阻断后，异常处理使用 stdlib logging 的 `logger.exception("...{}", server_id)`。项目日志转接器调用 record.getMessage，再次抛 TypeError，使后续提供商 335、337、358 等也被跳过。

## 修改

- `ModelProviderOperationRepository.acreate_share_reservation` 在赋值和摘要计算之前复用 `_utc(clock())`，使 expires_at、consumed_at、create_time、update_time 使用同一 UTC 整秒值。新计划跨 MySQL 秒精度读取后摘要稳定；不增加“容忍一秒”的读取兜底。
- 挂载 fanout 的 stdlib 日志改用 `%s`，保留原 traceback。单个提供商失败仍走原聚合错误处理，其余提供商继续调用受保护的 ashare。
- 原 UserPayload、挂载事实、租户范围、共享动作、投影账本、幂等和提供商锁全部保留。显式关闭 auto_distribute 或 Root 默认共享时，不新增模型共享。
- 无存储结构修改，没有新增权限豁免、直接 tuple 写入、旧计划摘要重签或锁清理。

## 验证

- 红测：模拟真实存储秒精度的 500000 / 999999 微秒用例失败；首个提供商失败后继续下发用例失败。另两个舍入边界通过，说明并非所有时间都会触发。
- 修复后定向：17 passed，覆盖 4 个时间边界、原摘要篡改拒绝、真实共享与挂载恢复链、首个提供商故障不阻断后续、两种关闭共享场景。
- 扩展共享/删除确认/投影/挂载 API 回归：117 passed / 6 failed；相同基线为 110 passed / 同样 6 failed，新增 7 个用例全部通过。失败来自既有 test_tenant_mount_service 的挂载/解挂/子树同步夹具，与本次差异无新增失败。
- Ruff check、所改 repository/测试格式检查、逐文件 arch-guard 和 diff 检查通过。未改前端，未运行前端构建。
- 按 sdd-code-review 七维度复核：边界、权限、并发、泄漏、测试、风格、文档均未发现本次新增阻断项。没有把 SQLite 仿真、MySQL CAST 或本地回归宣称为 116 新建租户 E2E。

## 部署与历史恢复边界

1. 本提交只防止新计划再次因精度损坏，并恢复 fanout 继续处理后续提供商；不会自动修复已有 PREPARING 记录和缺失共享。
2. 部署前保存目标源文件/镜像版本、计划只读快照及目标提供商实际共享名单。先部署修复，再验收新子租户挂载，检查对应共享关系及实际普通用户模型候选。
3. 历史 PREPARING 计划 12 仍受保护。恢复必须核对原操作、原操作者、签名证据、当前挂载事实和投影阶段；不能重签摘要、改成 COMPLETED、删除账本或解除锁。若需修正物理时间，必须作为单独带备份及 CAS 的维护步骤，保持原 plan_digest/request_hash，并证明恢复的原始时间与原签名一致。
4. 对提供商 335、337、358 的缺失授权，由有效 Root 超管通过原受保护共享命令重新下发，开启状态应重新确认/保存，不要先关闭再开启造成已授权租户被撤权。实际执行前仍需核对该提供商的活动计划；冲突时保留并恢复原操作。
5. 补齐后分别检查租户级提供商共享与用户级 DSH 可见范围。两者是不同条件；不能将 Root 可见范围或管理页的“Root 共享·只读”标签当作已完成全部授权的证明。

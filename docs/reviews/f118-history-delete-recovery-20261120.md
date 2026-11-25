# F118 历史删除投影受限恢复

- 基线：`origin/feat/3.1.0-beta1`，`b6c58466b262050419710a5aef82cda0dd45d690`。
- 范围：单文件维护逻辑 hotfix，对照 F118 AC-115/116/134。没有修改通用权限运行时、SQL 业务修复、物理清理、正式 M2 转换或计划格式。
- 用户要求：修复后验证并推送 beta1；165 环境暂不操作。本轮没有连接、部署或执行该环境。

## 问题与处理

历史 `permission_enabled` 标记可能只存在 `user:*` / `service_account:*` 中的一类。正常 RESOURCE_DELETE 编译两条 DELETE；OpenFGA 对缺失 tuple 的删除会拒绝整批，结果与编译的 BEFORE/AFTER 均不完全一致，原操作进入 FAILED_CLOSED。

`prepare_f118_history.project_history_delete` 先调用原 `project_delete`。只有该调用报告投影失败，且原快照已证明缺一类标记，才检查当前计划的 `history-delete:<plan checksum prefix>:<mode id>` 台账。重建并逐项比较预期 RESOURCE_DELETE 计划，检查 before/after checksum，再重验业务不存在、下游、镜像及 CURRENT Catalog pin；新出现的对象关系拒绝恢复。

修正只允许冻结技术标记键的 DELETE，通过已有 `inspect_failed_closed_recovery` / `recover_failed_closed_operation` 完成提案校验、原操作/版本栅栏检查、高一致性 AFTER 验证及原生 SQL finalize。不补回缺失标记，不跳过失败，不直接改 SQL 状态或直接写 FGA。恢复后的正常派生 cleanup 保持原逻辑。健康双标记基线后来变为 MIXED，以及不属于本计划的权限操作，不获得此恢复权限。

同份 plan、同 operator 重跑即可处理旧失败；已完成的原始删除与独立 purge 回执继续复用。plan 的 schema、checksum、字节内容和事件机制保持；CLI 失败原因不再为空，并可携带安全的 operation_id/projection_status，仍不输出 provider 异常正文。

## 验证

新增 `test/knowledge_unification/test_history_delete_recovery.py` 使用实际 SQLModel 表、ProjectionRepository、SqlProjectionScopeGuard、SqlProjectionFinalizer、F048PermissionRuntime 和 DeletedResourceCleanup。仅 FGA 网络以有状态传输替代，严格模拟“任一 DELETE 不存在则整批拒绝”，没有 mock 掉恢复或状态机逻辑。

新增 30 项通过，覆盖：

- 完整双标记、任意单类缺失、双类均缺失；预览不写，apply 正常完成，plan 字节不变，复跑无额外 FGA 写。
- 按旧脚本留下真实 FAILED_CLOSED 台账，再用同计划恢复；原操作 ID、版本与完整 tuple 台账保留。
- 修正写成功但状态更新前取消、SQL finalize 失败、SQL purge 失败，以及 FGA 写失败/响应丢失后的重试。
- 前一个资源已完成、下一个恢复中断，续跑不重复写前一个资源。
- 业务复现、下游增加、FGA 新关系、Catalog pin、租户、版本、操作围栏、scope、tuple 台账与 after checksum 改变时拒绝恢复；失败尝试后的事实变化也复核。
- 恢复提案 checksum 漂移及恢复前围栏漂移拒绝写入；日志只输出安全原因和操作标识。

相关历史准备、业务/物理修复及 F048 投影/恢复 CLI 组合回归先行通过 125 项；新增用例补齐后单文件最终为 30 项通过。扩展执行全部 `test_migration*.py`、`test_perm_migration*.py`、权限批量/投影、历史准备及 F048 投影 SQL/runtime/恢复 CLI 用例，1936 通过、1 失败（371.55 秒）。扩展进程启动后又补充的三个用例，已在最终 30 项单文件执行中通过，不对重叠用例累加计数。

唯一失败为 `test_migration_inventory_application.py::test_full_m2_keeps_original_default_sources_and_freezes_safe_after_commands` 的查询次数断言（预期 9，实际 6）。在独立、未修改的 `b6c58466b2` 工作树单独运行该用例，复现相同失败；其业务转换、冻结来源和不导出私有配置断言均已先通过。本轮不改该既有断言或相关实现，不宣称扩展套件全绿。

最终 Ruff 格式/检查（含 F821）、`git diff --check`、变更 Python 文件架构守卫与 CLI `--help` 通过。所选测试仅使用本地原生 SQLite 表及模拟外部端口，没有运行真实迁移或访问部署数据库。

### 异常规模成本

本机 SQLite + 严格 FGA 模拟，8/16 个均缺一类标记的删除资源，含同一父边修复及完整业务检查。SQL 为执行语句数；精确读取只统计投影传输的 read_present，非全部 FGA 盘点请求。内存为 tracemalloc Python 峰值，不是进程 RSS；耗时仅用于本机比较。

| 异常资源数 | SQL | SQL commits | 精确关系读取次数 | 读取键数 | FGA 写请求（含拒绝） | Python 峰值 | apply 耗时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 8 | 679 | 155 | 57 | 107 | 25 | 1.50 MiB | 1.21 s |
| 16 | 1295 | 299 | 113 | 211 | 49 | 1.88 MiB | 1.74 s |

资源翻倍，新增 SQL 616、commits 144、精确读取 56、键数 104、FGA 写请求 24，均为每资源固定增量。正常路径不进入恢复检查，不增加恢复查询或全库扫描。原有 preview/apply/resume 性能测试同时纳入回归；此量测不替代生产克隆或真实 MySQL/DM8/OpenFGA 演练。

## Code Review Report

按 `.claude/skills/sdd-code-review/SKILL.md` 七维度检查，基于完整代码、测试、AC-115/116、设计与任务记录人工自审，无子代理。

| Dimension | High | Medium | Low | Status |
|---|---:|---:|---:|---|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

恢复范围由原计划和完整台账约束，原生服务继续拥有最终版本/操作围栏及 CAS。停所有写入方仍是维护前提，不将此适配解释为在线通用修复。脚本的附加事实检查仅位于异常路径，原 Run 与持久恢复协议不重建；DB/Redis/FGA 资源生命周期未改。

审查结论：PASS（针对本次变更；扩展回归存在上述已独立复现的基线失败）。

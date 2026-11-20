# F118 升级取消外部 DBA 证明：实施与审查

日期：2026-11-19。范围为用户确认的 AC-129–134，基线为 `4cca6c7b3c` 上本轮工作区差异；不是 F118 全特性重新验收。用户在需求审查后要求“修改脚本”，据此同步实施与设计。未执行116 apply、部署或服务启停。

## 最终行为

DBA/运维负责一致备份与可恢复性，完成后通知升级负责人。升级人员按升级指南完成停服、结构升级与历史准备后，仅传 Run 和实际环境执行正式预检；显式 apply 开始转换，冻结后以同 Run、原环境和操作者恢复。无需提交 backup/schema 证明，也无需生成输入描述符文件。

新 Run 明确写 `external_material_policy=not_required`，历史字段同时为空。未知策略、旧格式空值及新策略混入非空描述符均拒绝。内部旧调用提供成对历史字段时只作原 wire 身份兼容，不读取其指向的 DBA 证明对象。

旧 Run 省略描述符时，从原哈希校验的 plan 根读取历史字段；完整 baseline/plan 图、writer、环境、租户集合、权限 pin、业务事实和 checkpoint 校验继续执行。显式传入旧字段若不一致仍拒绝。新 CLI Run 拒绝旧证明参数，避免重新引入人工证明前置。

移除了外部证明对象读取及针对这些对象的身份校验；没有改变业务转换、权限批量提交、来源回填、锁、事务或 checkpoint 更新逻辑。实际数据库结构检查保留。迁移自己的快照、计划、制品哈希，以及历史准备的选中行/孤儿内容精确备份仍需保留。

## 验证

- 首轮三模块定向：101 通过，排除一项修改前已失败的查询次数断言。覆盖无证明的预检/执行、冻结后中断恢复、旧 Run 省略证明恢复、显式身份漂移拒绝及 codec 边界。
- 补充 SQL 转换与完整图读取两模块：30 通过，含10001文件的原生规模用例、未知提交与部分提交恢复；将“外部证明损坏必须失败”的旧期望改为“原冻结 plan 根/叶页损坏仍失败”。新增两根策略不一致拒绝。
- 迁移专项回归：78个测试文件，1868通过、1项已复现的基线失败单独排除，运行349.89秒。覆盖历史准备、盘点、冻结图、SQL转换、权限、引用、Coverage、规模与恢复路径。
- 扩大执行知识统一模块时，在3899项通过后中断；66项失败中，63项在未修改的 `4cca6c7b3c` 源码中复现，另3项为本次取消外部证明后需更新的旧测试期望，已在上述30项回归中通过。扩大执行并非全模块成功，不宣称全仓质量门通过。
- 修改前失败的迁移专项断言：`test_full_m2_keeps_original_default_sources_and_freezes_safe_after_commands` 要求默认配置查询9次，实际为6次；在原始基线同样失败，本次未修改该断言或为满足它增加冗余查询。
- 变更 Python 文件 Ruff、CLI `--help`、diff 空白检查通过。4个生产 Python 文件无架构守卫发现；测试 fixture 的原有直接 FGA import 被守卫按业务代码误报，其 import 与 HEAD 相同，不属于新增生产依赖。
- 补 TC-MIG-DBA-001–006，已检查新增行均为八列且以“待执行 / —”结束；现场执行不以本地结果代填。

本地为原生 SQL/盘点/编解码/迁移应用层及可替换 transport 验证；没有新增 HTTP/UI 行为。本地至 Coverage 的调用链不冒充真实 MySQL/DM8 与 OpenFGA 联装 E2E。新发行镜像、隔离旧库完整升级、真实故障恢复和开服验收仍按 T1048 执行。

## 七维差异审查

依据项目 `sdd-code-review` 清单人工检查本轮差异，不声称独立 agent 审查。

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

核对依据包括：新旧字段及错误策略、完整 SQL/FGA 与 pin 检查、冻结竞争和原 checkpoint 恢复、原结构化错误输出、1868项迁移回归、删除无职责代码、Ruff，以及需求/设计/升级文档同步。上述判断仅针对本轮差异和已列的本地验证；真实环境及既有基线失败边界见前文。

规模影响：未增加资源循环、SQL、远程调用或轮询；定向测试确认冻结图复核的 plan/baseline 根各读取一次，两个外部 DBA 证明对象读取为零。未对生产维护窗口作新耗时承诺。

## 最终验证记录

**Overall: PASS（本轮差异）**。迁移专项1868通过、1项已知基线查询次数断言排除；未发现本轮新增的未解决失败。此前扩大回归的63项基线失败未在本任务修改，全模块不宣称通过。

执行命令：从 `src/backend/`，使用空的本地验证配置与原虚拟环境，运行 `/tmp/f118-no-dba-evidence-migration-files.txt` 所列78个迁移相关文件；仅以 `-k 'not test_full_m2_keeps_original_default_sources_and_freezes_safe_after_commands'` 排除上述已单独运行并对照基线的查询次数断言。测试未连接生产存储。

本地日志：`/tmp/f118-no-dba-evidence-focused.log`、`/tmp/f118-no-dba-evidence-extra.log`、`/tmp/f118-no-dba-evidence-migration.log`；扩大及基线对照分别为 `/tmp/f118-no-dba-evidence-regression.log`、`/tmp/f118-no-dba-evidence-baseline.log`。基线采用 `git archive 4cca6c7b3c` 导出的原始源码，非在工作区撤销修改后重跑。

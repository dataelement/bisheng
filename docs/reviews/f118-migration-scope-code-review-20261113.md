# Code Review Report：F118 迁移范围收敛

**Feature**：普通迁移解除物理盘点依赖、新 Run 完整只读预检、聊天确认规则复核。

**Review scope**：审查时尚未提交的工作区相对 `origin/feat/3.1.0-beta1` 的实际差异，以及未追踪新增文件；使用 `git diff origin/feat/3.1.0-beta1`，没有用结果为空的 `base...HEAD` 代替审查。

**Base branch**：`origin/feat/3.1.0-beta1` / `0b78bd7acccd510d7f5014ea78f0af50ffd69efa`。

**Changed files**：审查快照20项，其中11个Python文件、9个设计/升级/审计文档；本报告与随后汇总的统一执行记录另计。

**Date**：2026-11-13（UTC+8）。

**Method**：按 `.claude/skills/sdd-code-review/SKILL.md` 七维审查，对照 AC-122/123、design D10/§7.2/§10、tasks T1041–1044、QA新增5例及聊天确认审计矩阵。

## Summary

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

表中计数为复核后尚未解决的问题。审查中发现的两个生产边界已修复并增加真实路径回归，见下文。PASS仅针对本轮代码与文档差异，不等于真实升级、部署或整套F118业务验收通过。

## 1. 边界条件

- 新 `physical_inventory_policy=bindings_only` 独立于已有 `preparation_policy_version=2`，没有改变marker恢复合同。codec只接受明确的新值，缺字段按旧 `legacy_physical` 处理；baseline与plan根策略不一致明确拒绝。
- 新策略在manifest叶页的section层拒绝任何physical页，包含空页；旧图缺少原physical资源集合仍失败，不通过删除字段降低证据要求。
- `freeze` 必须为真正布尔值。新Run预览仍执行schema、业务删除半态、历史准备、材料身份、SQL父链、权限和六类引用的完整预检；坏数据返回原明确错误，不改为“预览成功”。
- 备份/schema的Run、环境、writer、实际租户集合仍核对；新增租户后旧材料不能被重标为新范围的备份。旧Run复核保持原集合及不可变证据约束。

## 2. 权限与认证

- 本轮未新增HTTP入口、业务鉴权捷径或跨租户角色策略。移除的是普通资源ES/Milvus存在性、结构、计数及逐文件对象stat，不是SQL权限、来源主体、成员关系或租户归属检查。
- CLI仍使用原配置下的数据库、Redis、MinIO证据适配器和固定Catalog/model的权限读取组合，没有通过通用应用启动发布模型、创建默认数据或初始化RAG。
- 孤儿文件精确备份/物理删除仍由历史准备路径负责；正常迁移取消全库盘点不会绕过删除范围、原绑定、有效下游或共享存储保护。
- 创建/恢复回调仍使用原operation、版本、幂等键、scope、tenant及pin围栏；CURRENT系统资源不会通过巡检重授已撤销授权。修正的是旧测试的错误期待，未为让测试通过修改生产权限逻辑。

## 3. 并发安全

- 新Run预览与正式M2复用同一盘点、计划及图验证，预览仅替换页存储并跳过 `afreeze_all`；无SQL/FGA/MinIO持久写入。正式apply仍重新盘点、验证并冻结，没有消费上次预览的临时页。
- 同名Run在CLI初查后被其他维护事务冻结时，`freeze=False`分支明确报 `preview_requires_new_run`，不将冻结图复核冒充当前全扫描。
- 私有临时页由同步context管理，正常返回、异常及取消均执行清理；临时descriptor不在CLI结果中作为可恢复证据输出。SQL事务的清理仍由原session上下文完成。
- 运维停全部写端/消费者的前置保持。此次没有增加队列巡检、自动停服或后台恢复调度器，也没有借恢复覆盖后续合法操作。

## 4. 信息泄漏

- 临时目录0700，页文件在写内容前设为0600；文件名由对象键SHA256形成，调用方对象键不能成为本地路径。
- 原canonical、对象键、摘要及16MiB单页边界继续生效；本地页篡改仍被原不可变摘要校验拒绝。读取既有材料仍使用原证据适配器。
- 新预览字段只说明验证范围和完成程度，没有输出临时目录、SQL连接信息、原配置或凭据。测试统一使用空配置和拒绝真实IP连接的plugin，不依赖私有服务配置或生产中间件。

## 5. 测试覆盖及独立执行

本审查者实际执行：

| 选集 | 结果 | 能证明的范围 |
| --- | --- | --- |
| `test_migration_preview_artifacts.py`、`test_migration_binding_policy.py`、`test_migration_cli.py` | 23 passed，0 skipped，6.73秒 | 新旧图策略、SQL-only原生M3及重放、完整预览零持久写入、实际坏链阻塞、并发冻结、私有页校验和成功/异常/取消清理 |
| permission recovery intent / projection service / SQL runtime / system reconcile及maintenance pin | 52 passed，0 skipped，1.24秒 | 迟到补偿/收尾不覆盖后续撤权、同原operation恢复、CURRENT不重授、调用方上下文恢复 |

两组选集均使用 `config=/private/tmp/f118-scope-audit-tests.yaml`、`PYTHONPATH=/private/tmp:.`、`-p f118_scope_no_network`。23项的独立JUnit为 `/private/tmp/f118-migration-scope-review-20261113.xml`。

同时核对历史规则审计专项日志与JUnit：98 passed、2 skipped。统一组合回归已结束：82个测试文件，1846 passed、2 skipped，313.64秒，退出0；JUnit记录1848项、0失败、0错误，两项跳过均为缺少dmSQLAlchemy的DM8方言测试，未写成DM8执行通过。原有111015条弃用警告保留记录，不宣称零警告。以上专项与组合选集存在重叠，不相加包装成新的通过总数。最终组合日志为 `/private/tmp/f118-scope-audit-regression-20261113.log`，JUnit为同名 `.xml`；范围见[本轮收敛修复记录](f118-migration-scope-fix-20261113.md)。

旧测试调整保留了有效断言：NON_CURRENT先由原bootstrap校验明确拒绝，不用无约束AsyncMock假通过；合法原operation先验后续办另有正例；租户上下文以调用前实际None/99分别验证成功及异常恢复，没有修改生产代码去满足错误的固定99期待。

## 6. 代码风格与架构

- 阅读了 Inventory `arun/_arun/_tenant/aiter_frozen_pages`、codec策略解码、physical verifier和CLI `_runtime/arun`，以及新增 `preview_artifact_store`、`_PreviewStorage` 全部方法。未发现遗漏的普通ES/Milvus初始化或文件stat接线。
- 使用独立临时分页适配器复用原存储/codec/图校验，没有复制另一套较宽松的预检逻辑。缓存完整库存的内存方案未引入；原分页上限及单页内容限制保持。
- 当前11个Python变更文件的 `ruff check`、`ruff format --check` 均通过；仓库相对路径逐文件arch-guard无诊断，生产文件绝对路径检查亦通过。
- **保留并解释既有守卫提示**：绝对路径运行 `test_migration_inventory_application.py` 会触发RULE-9，因为路径祖先含 `/bisheng/`，而旧测试本来就直接使用FGAClient构造隔离transport。将远端原文件放到同样含 `/bisheng/` 的基线路径后，提示完全相同。未修改守卫、未将其报成新增业务C4违规，也不宣称所有绝对路径检查零提示。

## 7. 文档及历史确认范围

- Spec AC-122/123、design D10/§7.2、风险表和本轮修订记录同步了选择理由、数据流、输出字段、旧证据默认行为、反直觉边界及何时重审。
- 升级指南活跃主流程已纠正“ES/Milvus必须可读”和“无Run预览不扫描”的旧口径，首部链接指向新的当前流程图；有明确日期的旧演练内容保留历史边界。
- 新增QA5例的八列名称与模板相同，每行8列，结果字段仍为“待执行 / —”；本地自动化通过没有覆盖成QA现场执行完成。
- 已核对37项矩阵及后续频道、前端保存、配额、角色和现场验证条目。它区分审计基线遗漏、本轮实现、既有回归定位、现场执行及独立事项；所列测试文件路径均存在。
- 没有发现“37项全部完成现场验收”的越界声称。角色跨租户业务方案、OpenFGA镜像索引交付、不能安全证明的历史数据处置和全平台后台自动恢复仍单独列明；不能把脚本接线当成这些事项已完成。

## 已修复的审查发现

| 发现 | 影响 | 修复与证据 |
| --- | --- | --- |
| fresh preview初查无Run后，同名Run被并发冻结 | 冻结图复核可能错误输出为当前完整扫描 | Inventory拒绝该路径；`test_new_run_preview_rejects_freeze_committed_between_its_two_transactions`通过 |
| 新策略仅逐记录拒绝physical，空叶页未经过观察器 | 新图可夹带与策略不符的空physical页 | section层提前拒绝；`test_binding_only_policy_rejects_even_an_empty_physical_leaf`的baseline/plan两例通过 |

## 本地限制与后续验证

- 未构建或发布包含本轮代码的新镜像；本轮未登录116、109或其他服务器，也没有执行现场迁移或服务启停。
- SQLite原生事务、ASGI/HTTP传输替身和禁网测试不等于真实MySQL、DM8、OpenFGA、MinIO、ES/Milvus验证。DM8真实执行待中央环境；本报告不以跳过结果替代。
- 当前已迁移116数据的现状扫描不能证明未迁移旧版数据完成全部转换；仍需固定镜像及未迁移快照的隔离升级、恢复和关键业务链验证。tasks T1044保持未完成。

## Overall: PASS

无未解决HIGH/MEDIUM发现。本轮代码和文档可以进入交付流程；本结论不批准跳过固定镜像验证、旧快照升级复演或现场业务验收。

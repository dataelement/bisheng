# 116 环境 F118 升级问题与处置记录

记录日期：2026 年 11 月 11 日。时间均为 UTC+8。

**状态：批准的数据清理和备份已完成；已按用户确认的保留方案修复历史空模型兼容，42 个历史模型名配置已按补充授权清空；继续预检被 143 个资源引用的不兼容旧索引及其他数据一致性问题阻塞，尚未恢复业务。** 本记录保留 192.168.106.116 升级中遇到的真实阻塞、数据处置范围和备份边界，供判断应改进迁移脚本、历史业务清理逻辑还是现场数据。当前镜像已经包含 F118；本次需要执行知识空间统一与全平台 `use` 退役，单独发布 OpenFGA 模型不足以完成升级。

## 环境与最初报错

部署目录为 `/opt/server/bisheng-test`，数据库为 `langflow`，共有 30 个实际租户。业务容器包括 `bisheng-test-backend`、`bisheng-test-backend-worker` 和 `bisheng-test-backend-worker-ocr`。前端及数据库、Redis、OpenFGA、ES、Milvus、MinIO 等中间件保持运行。

后端镜像是 `cr.dataelem.com/dataelement/bisheng-backend:release`，实际镜像 ID 为 `sha256:4ed6b328c478abd7942f9b05818f26cae0b0444146c8904d1a6c1966d9131f7b`，构建于 2026-11-10 22:40:43 UTC+8。升级期间使用同镜像、同配置的临时容器 `bisheng-test-permission-upgrade`，停止原 API 和全部 Worker，保留队列数据。

最初日志为 `authorization_model_migration_required`，随后 `permission_runtime` 初始化重试三次失败，API lifespan 退出。OpenFGA HTTP 请求返回 200，故本次初始阻塞来自权限模型版本不匹配。

| 项目 | 实测值 |
| --- | --- |
| OpenFGA Store | `01KQ3ZRQ9VY0FJJ46V8NW98M7M` |
| 升级前模型 | `f048-v6-app`，模型 ID `01M635XD9X42DD23RE73H7VTS1` |
| 升级前模型 checksum | `1d991de1c5a752936a75abce7cec45096d15e5c6283e9ba4839ffaf0ada7cfe6` |
| CURRENT Catalog | 198，指向授权模型发布记录 7，未 write fence |
| 新镜像声明模型 | `f048-v6-app-f118` |
| 数据库与镜像 Alembic heads | `f118_knowledge_delete_execution`、`v310b1_merge_work130_heads`，两者集合一致 |

数据库结构升级已执行。当前镜像具有两个 head，不能直接套用旧文档中的“单一 head”文字判断是否漏 DDL。

## 执行顺序与权限恢复

10:41 左右完成服务与迁移进程复核。10:42 开始停服维护。最初仅做只读排查和脚本预检；通用模型发布 dry-run 在全 Store 扫描期间停止，没有执行模型发布。

排查时存在 3 条活跃投影：2346、2347 为 `COMMITTED`，2470 为 `STAGING`；另有 11 条 `FAILED_CLOSED`。12 个资源镜像处于非 CURRENT 状态。还有一条排查前已经存在的首次 F048 迁移运行记录：run 2 为 `SOURCE_VALIDATING/RUNNING`，无 target model，扫描和迁移计数为 0，租约于 10:35:59 过期，现场未发现该迁移进程。该记录未被冒充为成功完成，也未续跑首次 F048 数据迁移。

### 官方恢复工具遇到的问题

1. `recover_f048_failed_closed_projection.py` 构造完整业务权限 facade 时，旧 Catalog 中的 `use` 被新代码判定为 `action codes are not registered: ['use']`，尚未进入投影恢复就失败。
2. 为恢复旧版本冻结投影，临时运维适配器只组装原有 SQL/Redis/OpenFGA 投影服务，保留 SQL CURRENT pin 校验、原不可变模型 checksum、持久 tuple 账本、资源版本和操作围栏、修正提案 checksum 等检查。旧模型操作逐一校验对应 SQL 发布记录与 OpenFGA 模型内容，没有更改线上模型配置。
3. 技能 134 的修正预检发现 OpenFGA 已达到完整 AFTER 状态、需要修正的 tuple 数为 0，但 finalize 仍报 `Visible source recovery owner state is incomplete`。旧创建补偿留下的 Grant 是 `state=PENDING, projection_state=FAILED_CLOSED`，普通 finalizer 只推进 `PROJECTING` Grant，导致其可见来源仍引用 PENDING 主体。
4. 对限定的内置技能创建记录核对真实业务行、所属租户、冻结来源和原操作围栏后，恢复其记录中的创建中间状态，再调用正常投影域服务完成 finalize。未新增授权主体或推导新授权意图。

### 已恢复的资源

| 操作 ID | 租户 | 资源 | 处置 |
| --- | --- | --- | --- |
| 5、6 | 1 | folder 97253、95113 | 原模型冻结移动计划已达到 AFTER，完成状态收尾 |
| 7、25、33 | 1 | knowledge_file 94746、86941、94860 | 原模型冻结移动计划已达到 AFTER，完成状态收尾 |
| 2341、2343 | 63 | linsight_skill 128、131 | 收尾冻结创建授权与可见来源 |
| 2346、2347、2348 | 64 | linsight_skill 134、135、136 | 收尾冻结创建授权与可见来源 |
| 2470 | 1 | knowledge_file 97951 | 依原持久账本 reconcile，完成创建 |
| 2731 | 65 | linsight_skill 151 | 收尾冻结创建授权与可见来源 |

12 条全部完成后，11,441 个资源权限镜像均为 `CURRENT`，活跃投影为 0。仍有 2 条历史失败删除操作账本：1388、2473；它们未持有当前资源围栏，未被直接删除或标记为成功。11 条恢复预检的 tuple 修正数均为 0；2470 通过正常 reconcile 续跑。

## F118 正式迁移预检与数据处置

正式入口是 [`unify_knowledge_spaces.py`](../../src/backend/scripts/unify_knowledge_spaces.py)，对应[升级说明](../../features/v3.1.0-beta1/118-knowledge-space-unification/upgrade-guide.md)。运行 ID 为 `116-f118-20261111`，writer contract 为 `f118-v1`，审核操作人为现有 user 1。运行参数使用同环境配置，原配置文件与凭据没有写入本记录。

用户最初明确要求“不用备份执行升级”。为保留事实，本次运维材料记录 `backup_performed=false`、`restore_verified=false` 及用户的免备份指令，并核对实际数据库 schema heads。没有把免备份声明伪造成成功备份，也没有执行完整环境恢复演练。

正式预检首先报 `10998 / unification_resource_file_parent_invalid / id=81`，发生在 M2 基线冻结和 M3 数据转换之前。随后只读汇总原完整性检查，集中列出全部命中项；正式迁移的校验没有被跳过或改成放行。

### 第一批已批准并执行的数据修复

用户明确批准清理 10 条父知识库缺失的历史文件/目录及其无效关联，并修正 43 条跨租户字段。单事务锁定精确记录，核对没有有效资源权限镜像或业务引用后执行。

| 项目 | 行数 | 实际修改 |
| --- | ---: | --- |
| 父知识库不存在的 knowledgefile | 10 | 删除元数据 |
| 上述文件的失效 knowledge_document_version | 22 | 删除关联版本元数据 |
| 上述版本唯一对应且父库不存在的 knowledge_document | 22 | 删除文档元数据 |
| knowledgefile 的租户字段 | 43 | 从错误 tenant 18 改为父库与既有权限镜像共同确认的 tenant 1、13 或 14 |
| 对象存储文件 | 0 | 未删除或修改 |

10 条文件 ID：`81, 83, 84625, 84626, 84665, 84673, 84674, 84675, 84676, 96572`。

43 条归属修正 ID：`86050–86072, 86159, 86160, 86171, 86173, 86176, 86177, 86178, 86187, 86188, 86190, 86191, 86192, 86194, 86195, 86196, 86197, 86198, 86199, 86200, 86201`。此处区间 86050–86072 共 23 条；其余 20 条。每条都逐一验证现有 F048 权限镜像所属租户等于父库租户，保留原更新时间，没有批量移动授权。

**备份边界：这批按当时免备份指令已提交，未保存删除前完整行。** 现有记录只能证明 ID、行数、关联检查和所执行 SQL 的条件，不能替代这些已删除行的全字段备份。后续生成的备份不覆盖这批已删除记录。

### 第二批预检发现的失效关联

| 检查及分类 | 行数 | 判定依据 |
| --- | ---: | --- |
| 文档父库缺失 | 1,267 | 父知识库不存在，关联版本均无有效物理文件 |
| 有父库但已无有效文件的文档 | 148 | 每个文档仅 1 个版本，该文件行已经不存在 |
| 以上孤儿文档相关版本 | 1,274 | 文件行缺失 |
| 有父库文档相关无效版本 | 148 | 文件行缺失 |
| 文档行缺失的版本关系 | 1 | version 2782 → 缺失 document 2758；真实 file 89579 保留 |
| 文件目标缺失的标签关联 | 159 | Tag 存在，KnowledgeFile 不存在 |
| 标签目标缺失的标签关联 | 48 | KnowledgeFile 存在，Tag 不存在 |
| 标签和文件均缺失的标签关联 | 31 | 两个关系目标均不存在 |
| 已删除空间的成员关联 | 165 | `business_type=space` 的父知识库不存在 |

合计文档 1,415 行、版本关系 1,423 行、标签关系 238 行、空间成员关系 165 行，共 3,241 行。只读预检同时确认 `controls` 在空间成员父关联处失败；业务来源孤儿检查、来源租户检查和权限全局孤儿检查均通过。取得最新授权并完成备份后，清理事务重新锁定完整行、逐字节匹配备份，再精确删除上述 3,241 行，提交成功。日志为 `logs/invalid-relations-cleanup.log`。实际 file 89579 保留，没有对象存储修改或授权主体变化。

用户询问这些检查是否属于知识库升级为知识空间的脚本，得到明确说明后，最新授权为“清理吧，但是记录下这个升级过程中的问题和失效关联数据备份”。因此这批先生成全字段备份并核验，再清理；备份并不代表获得未来自动恢复或自动清理其他异常数据的授权。

## 备份与执行材料

第二批备份包含四张表精确选中行的全部字段：`knowledge_document`、`knowledge_document_version`、`taglink`、`space_channel_member`。

- `rows.json`：完整原始行；日期、Decimal 和 bytes 使用带类型的编码。
- `schema.sql`：备份时的四张表结构。
- `restore.sql`：完整字段的 INSERT，遇到主键冲突会失败；未执行恢复。
- `manifest.json`：环境、数据库、捕获时间、各表行数、SHA256 和第一批未备份边界。
- `SHA256SUMS`：逐文件校验。

运维脚本先在事务中锁定和导出精确记录。复制到宿主机持久目录并执行摘要校验后，再单独执行清理。清理事务会重新读取完整行，与已备份内容逐字节比较，防止预检后变化或误删其他记录。原始行备份包含业务元数据，权限设为目录 700、文件 600，不提交 Git。

宿主机持久目录为 `/opt/server/bisheng-test/upgrade-records/f118-20261111`，备份位于其 `invalid-relations/`，脚本和日志分别位于 `scripts/`、`logs/`。`rows.json` 的 SHA256 为 `87f96e66e29d831d6950d2f38244ab3b29b645f9e79c5f03149ba9bc2b2a7989`。清理前，宿主机上 `rows.json`、`schema.sql`、`restore.sql`、`manifest.json` 的 `sha256sum -c SHA256SUMS` 均为 OK，完整备份约 1.5 MiB。`logs/backup-verification.log` 保存该校验输出。

这份备份仅覆盖第二批待删除的失效元数据，不是 SQL/OpenFGA/索引/对象存储的完整一致恢复点。尚未实际执行恢复 SQL，也不能把摘要通过视为恢复演练通过。报告不包含数据库口令或配置原文。

## 清理后的新阻塞

清理后再次调用官方原有全局检查，`resources`、`controls`、`source_orphans`、`source_tenants`、`permission` 五项全部通过。日志为 `logs/post-cleanup-integrity-checks.log`。这只证明全局关联检查通过，尚未完成后续全量逐租户盘点、物理索引/对象验证和业务引用对账。

正式 M2 接着在构造 Catalog 退役计划时返回 `25010 / f118_permission_unexplained_empty_model`。定位为 [`f118_plan.py`](../../src/backend/bisheng/permission/migration/f118_plan.py) 的 `_validate_catalog()`：没有有效动作，也没有受控纯可见标记的模型会被拒绝。

| 字段 | 实测值 |
| --- | --- |
| 模型名称及 key | `yifei`，`legacy-custom-custom_069ecb78-ad26e3100f` |
| CURRENT 模型行 | 3431，Catalog 198 |
| 状态 | CUSTOM、PLATFORM、active=true、allow_same_level=false |
| 动作与等级 | selected/effective actions 均为空，derived_level=NULL |
| 纯可见来源字段 | visibility_only_resource_types、visibility_level、retired_use_level_floor 均为 NULL |
| 全部 Grant 引用 | 366 行，其中 2 行 ACTIVE；Assignee 2 行，VisibleSource 2 行 |

两处 ACTIVE 直接授权如下，均为租户 1：

| Grant | Source | 用户主体 | 资源 | 原模型 HIGHER_CONSISTENCY visible 检查 |
| --- | --- | --- | --- | --- |
| 1023 | 2139 | user 747 | channel `3021e91d61bd463fb0fd81be4567eb45` | true |
| 1040 | 2163 | user 745 | channel `3ad3af596dab40179a2fda1e73497d92` | true |

**这两条具有真实可见效果，不能按失效关联删除。** 未删除模型、撤销这些授权、猜填等级或跳过迁移校验。

旧模型策略的 `_custom_model()` 仅在 `model.active and selected` 时添加无有效动作 blocker，因此可以保留“active、selected 为空、无等级”的历史自定义模型；F118 的基线校验却拒绝该状态。模型历史中也出现过非空动作/不同等级的版本，但 CURRENT 已明确为空，不能从历史最高等级推断本次应当赋予的等级。

[设计 §7.3.2](../../features/v3.1.0-beta1/118-knowledge-space-unification/design.md) 要求纯可见标记具备受控来源及原合法等级 1–4，并拒绝任意未分级空模型。本次现场显示，这个升级前已存在且实际有可见贡献的状态，需要明确兼容合同或通过正式目录流程重新配置/撤销后再迁移。直接放宽校验、补一个默认等级、删除仍有效的授权都不能当作普通脏数据清理。

只读快照位于归档的 `permission-blocker/`：包括完整 CURRENT 目录和授权模型发布记录、动作/范围、模型/动作关系、该模型历史记录、366 条 Grant、全部关联来源、原 OpenFGA 模型、两处 channel 的原始 tuples 和实际检查结果。该快照是限定范围的诊断证据，不是完整 Store 备份。首次诊断曾请求旧 channel 模型不具备的 `use` relation 并收到 400；该只读失败日志保留，最终检查只验证实际存在的 `visible`。

归档另含实际镜像中的 17 个相关源码文件，位于 `source/`，避免把当前工作区代码与运行镜像默认为同一版本。关键镜像内文件 SHA256 如下：

| 文件 | SHA256 |
| --- | --- |
| scripts/unify_knowledge_spaces.py | `bc1511a66f3affcaa8b56c88bb6e99b5604e81185558c2c5330de242bdbfafcd` |
| bisheng/permission/migration/f118_plan.py | `325145c2fb52e494054c9a1922318a4c80ee8bb33823649f49c8c6875415025b` |
| bisheng/permission/application/sql_runtime.py | `5fe5be54a6ce5388debae428780ef2f77e906cdd333bebd61b3234443f4fa3d1` |
| bisheng/permission/domain/services/model_policy.py | `2f7cb89bfcb68e63f060bffd0039dff2889ceb73f75fb1b83696d9a009936819` |

## 对迁移脚本和业务逻辑的评估点

以下是基于本次复现的改进候选。第 10 项的保留兼容已获用户确认并实现；其他候选不在本次代码改动范围。

1. **提供完整的只读问题清单。** 当前资源全局预检发现首个异常即返回 ID，现场必须额外汇总才能知道 53 条文件问题之外还有 3,241 条关联问题。可在正式冻结前提供稳定分类、精确 ID、依赖范围及摘要，同时保持正式转换拒绝不一致数据。
2. **将失效元数据处置做成明确的独立运维流程。** 对目标已证实不存在、没有有效业务承载的关联，可提供默认 dry-run、全字段导出和摘要确认的 opt-in 清理或隔离工具。真实跨租户冲突、无法证明归属、有效资源或权限缺口仍须阻塞，不能统一静默忽略。
3. **定位历史删除未清理链。** 已删除知识库留下文档/版本和空间成员，删除文件或标签留下 TagLink。需要分别核对历史业务删除、异步清理和测试数据创建是否覆盖这些表。现场结果证明存在残留，尚不能仅凭此确定是哪段业务代码造成。
4. **租户纠正必须有双重依据。** 本次 43 条记录的父库与既有权限镜像一致，只有 file.tenant_id 错误。后续工具应保留这项证据要求，不能简单把所有子表 tenant_id 改成父表值。
5. **恢复工具应兼容升级前目录。** F118 新 facade 不能解析旧 `use` 动作，妨碍在发布新模型之前恢复旧投影。可将恢复组合限制在版本 pin 与持久投影协议，不依赖新版本的完整动作目录解析。
6. **原子恢复创建者和来源状态。** 本次发现创建补偿将 PENDING Grant 的 projection_state 改为 FAILED_CLOSED，而 generic finalizer 只处理 PROJECTING Grant。应基于冻结创建账本，原子恢复 Grant、Assignee、VisibleSource、资源版本和操作终态，避免现场修复中间状态。
7. **更早说明 F118 的专用升级入口。** 通用发布工具可以识别旧目录含 `use` 而当前代码退役该动作，提前指出必须运行知识空间统一流程，避免先写新模型后才遇到目录解析失败。本次没有通过该工具 apply。
8. **核对 D0 启动说明与代码。** 日志称 predecessor model 可启动以供运维迁移，但当前 lifespan 的 `_prepare_native_reference_permissions()` 强制初始化 permission runtime 并退出。升级说明和启动行为需要一致，且不能以开放旧授权检查绕过迁移。
9. **防止误启第二次首次 F048 迁移。** 本环境已有 completed run 1 和完整 CURRENT 控制面，却遗留新的 source-validating run 2。应核对工具是否仅按“目标 checksum 不同”判断可迁移，区分首次 F048 数据转换与后续 F118 版本升级，避免错误入口。
10. **明确历史无等级空模型的迁移合同。** 本次 `yifei` 并非仅有无人使用的空定义，两个 channel 的可见检查实际为 true。需要评估是否保留这种无管理等级的历史可见语义，以及来源后续如何按原边界撤销；或由管理员先在兼容旧版本的正式目录流程中处理。当前合同下脚本拒绝该状态有明确依据，不能简单定性为应删除的数据，更不能把所有空模型自动授予 1 级。

## 兼容处理前的阶段结果

已完成 12 条资源投影恢复、第一批 10 条孤儿及其 22 条文档/22 条版本的清理、43 条归属纠正，以及第二批 3,241 行全字段备份和精确清理。五项全局完整性复验通过。

兼容方案获批前的最新阻塞为历史空模型 `yifei`。`knowledge_unification_run` 中本次 run 的行数仍为 0，说明尚未完成正式 M2 全局冻结；M3 知识库类型转换、use 退役、OpenFGA 模型发布、CURRENT 目录切换和 M4 覆盖签证均未执行。CURRENT 仍为 198，仍指向原模型发布记录 7，未 write fence。

API、Worker 和 OCR Worker 仍停在维护状态，没有在不匹配的目录/模型下开放业务；前端和中间件仍运行。截至该阶段未修改 F118 产品迁移实现或关闭其完整性检查，仓库仅新增本问题记录；现场临时运维脚本和日志均归档。是否兼容该空模型或通过正式权限流程调整其业务语义，需要进一步评估，不能把本次清理及备份完成表述为整套环境升级成功。


## 用户确认的兼容处理与续跑（2026-11-11）

用户明确选择“按照兼容方案处理”。兼容修复已提交 `6f7fbaff2b` 并快进到本地发版线 feat/3.1.0-beta1；代码/七维审查见 [兼容审查记录](./f118-legacy-empty-model-compat-20261111.md)。未 push。本地无关工作区修改保持原状。

处理范围为 5 个权限文件：规范空 CUSTOM 定义保留原动作空集和空等级；原来源必须有完全匹配的 ACTIVE 可见投影证明才保留；GrantService 的新增、转入、管理/撤销规则不变。SQL 名册按原游标有界读取，再批量验证精确目标/祖先作用域的证据；visible 摘要保留来源，具体动作不因兼容新增。

现场只读预检发现另外两种合法旧状态，均补充精确兼容并留日志：

1. 首次 F048 writer 生成 `migration:{source_type}:{source_ref}` locator、完整 assignee 语义 JSON 指纹，与在线新增授权的 canonical locator 不同。F118 原逻辑误用后一格式校验前者。现校验两种明确协议，主体/类型/关系/children/protected/projected_subject 等字段必须一致；旧 locator 和 fingerprint 不改写。
2. 全局有效模型在特定目标上可没有适用动作。例如 `legacy-system-viewer-d35ca5051b` 在 channel 上为该状态，仍有原可见贡献。只保留存在原 ACTIVE 精确证明的贡献，维持原等级和全局动作，不发明纯可见标记或扩大目标分配资格。

新增 38 项兼容测试全通过，关键选集 86 passed。扩展选集 1,246 passed、67 failed、5 errors、10 skipped，与原基线的 72 个失败/错误 ID 完全一致，新增失败 0；不把全套权限回归称为全绿。Ruff、格式、diff-check 及架构 guard 通过。

116 镜像与当前发版线在 control_state.py 和 runtime.py 各有一处后续无关修复差异。现场补丁从实际镜像原文件仅移植本兼容 hunks，其他 3 文件与基线完全相同；原文件/部署文件逐一校验 SHA256，原文件备份和清单在 `compatibility-fix/`。新长寿命运维容器为 `bisheng-test-permission-upgrade-v2`，避免原两小时临时容器到期中断迁移。该容器的 unhealthy 是维护 sleep 入口不提供 HTTP 的预期现象，不代表业务服务已恢复。

正式续跑前只读验证 Catalog 198 的空模型元数据完全相同、Grant 1023/1040、Source 2139/2163 原 ID 不变、两处可见差异为 0，原 user747/user745 的 HIGHER_CONSISTENCY visible 仍为 true。随后使用原材料和同一 run `116-f118-20261111` 执行官方 apply；尚未冻结前不使用 resume，也未重新生成免备份/结构材料。

原 `f118-20261111.tar.gz` 为清理后、兼容前的不可变归档，保留不覆盖；最终续跑结果与兼容补丁另归档。以上新增内容不改变第一批原始行未备份及第二批 3,241 行已备份的边界。

只读规模核验：当前原 OpenFGA Store 共 142,855 条 tuple。全量盘点必须完整读取该 Store，不用两处授权抽样或短路代替正式 M2；日志按每 5,000 条记录进度。


## 全量扫描后的旧 embedding 名称阻塞（后续已获批清空）

加载兼容补丁的官方 apply 已完整读取原 Store 的 **142,855** 条 tuple，随后进入 tenant 1。预检在 `ResourceConversionPlanBuilder.add_resources → KnowledgeReferenceSourceOwner._snapshot → extract_knowledge_model_references` 报 `10994 / knowledge_model_configuration_invalid`，原因是知识资源的 `model` 为旧名称而非正整数模型 ID。日志位于 `logs/official-upgrade-compatibility.log`。没有跳过该校验，也没有冻结或进入 M3。

只读汇总全部 2,647 个知识资源，发现 **42 条**不符合现模型引用合同：41 个 type 0 普通知识库、1 个 type 1 QA 库，均为 tenant 1，全部没有 knowledgefile。名称分布：

| 旧 model 值 | 数量 |
| --- | ---: |
| bge-large | 4 |
| bge-large-zh | 14 |
| embedding-host | 15 |
| gte-large | 2 |
| jina-embeddings-v2-base-zh | 6 |
| text-embedding-ada-002 | 1 |

当前模型登记没有对应的原名称/供应商映射，全局 initdb_config 的 knowledges.embeddings 和顶层 embeddings 也均为空。仓库确有历史 `scripts/convert_sys_embeddings.py`，注释为旧 0.3.4 升级步骤，依赖原 embedding 配置生成登记并把旧名称替换为 ID；当前 `settings.get_knowledge()` 已返回 KnowledgeConf，不再是该脚本所期待的带 get() 的旧字典。不能直接重跑该旧脚本，更不能把名称模糊匹配为其他租户的相近模型或强行指向当前默认 934。

这些记录证明存在未转换或后续混入的旧配置；不能单凭它们断定整套历史升级曾完全漏执行某个脚本。当前 create/update 及 embedding 执行路径也要求模型 ID，该旧值并不是 F118 新增的可用模型能力。

已在任何修改之前备份 **42 条 knowledge 全字段记录**、实际表结构、拒绝主键冲突的整行恢复 SQL、只恢复 model 字段的条件 UPDATE SQL及清单，并核验服务器持久副本的 5 个文件 SHA256。位置为 `legacy-embedding/`，rows.json SHA256 为 `c7891bf7b37753e6ffd8c2e1590ba9a2c2ae97e4a0b1dc9b4fc657463a9a7366`。42 个 ID 为：174、195、210、217、218、220、222、242、243、253、257、272、287、318、395、399、525、542、570、574、575、577、581、590、592、594、596、598、600、611、612、829、873、879、881、888、903、904、905、929、940、1092。

准备的具体处置方案是只将上述失效 model 设为 NULL，保留知识资源、Grant/Source、索引与对象存储，不替换 embedding、不重建向量；之后需管理员为这些资源重新配置合法模型才能使用。该变化涉及仍存在的知识资源配置，超出此前 3,241 条孤儿元数据清理与空权限模型兼容范围，因此已请求用户补充确认；**尚未清空或删除这些资源**。对应脚本 `scripts/bisheng116_legacy_embedding.py` 默认只备份，执行清空需显式 apply 参数且逐字核对备份与 live 原记录。

在等待决定期间，其他租户按原 `_tenant` 逻辑执行独立只读诊断：原权限 pin、SQL/引用、来源编码与实际物理存储检查保留，输出仅计数/错误。诊断不创建 frozen run、不写 artifact 或业务数据、不替代正式 M2，之后正式 apply 仍需完整重读 Store 和全租户。


## 其他租户只读诊断及全局结构清单（未处置）

不含 tenant1 的 29 个租户中，24 个完成诊断阶段校验，5 个被原校验阻断。此诊断不是全局正式 M2 成功或租户 ready，不能据此开放业务。

| 租户 | 原错误 | 已定位证据 | 处理边界 |
| --- | --- | --- | --- |
| 13 | `migration_preflight_model_physical_parent` | assistant `e029e59bda05450aaf82ac11d252c3a7` 的 `model_name` 显式指向 model800；该模型及 server302 均属 tenant18 | 真实跨租户引用，不能当 Root 共享或修改模型归属。源模型自身父关系正常，需决定修正来源配置或如何记录历史失效。 |
| 18 | `f118_permission_existing_space_scope_hole` | 现有 space3426，mode7592；ACTIVE Grant14827 使用 `legacy-system-viewer-d35ca5051b`，在 space 上无适用动作、原等级2，已有1个ACTIVE来源 | 该闸门明确阻止原无动作模型在现有空间被新增的纯可见元数据改变适用范围；本次未移除闸门或删除该有效授权。需独立确认兼容边界。 |
| 20 | `conversion_plan_tag_container_missing` | Tag553 的 knowledge_space 容器3389不存在 | 属于未纳入原 238 个失效TagLink的 Tag 自身残留，已记录并备份，未删除。 |
| 25 | `migration_preflight_invalid_file_depth` | 实际文件层级与路径长度不一致，完整 ID 见 structural-diagnostics.json | 需保留真实文件与目录关系，不能把“层级错误”当作文件可删除证据。 |
| 60 | `permission_namespace_original_container_mismatch` | mode11017 指向已不存在的 knowledge_library4301，旧操作2042 | 权限镜像残留；需连同 Grant/Source、可见聚合和投影账本核对，不能仅删 SQL mode 后假定 FGA 一致。 |

对全环境同类结构问题的补充只读汇总如下，未执行修正或删除：

- 文件元数据 **112 条**：tenant1 为111条、tenant25为1条；9条 level 与路径长度不符、103条祖先缺失或归属不一致。它们是仍存在的文件，不能按无效文件清理。
- 所属知识容器缺失的 Tag **170 条**：tenant1 为169条、tenant20为1条。此前清理的238条是 TagLink，不是这批 Tag。
- 业务目标已不存在的权限模式 **328 条**：tenant1 为323条、tenant60为5条；类型为 folder14、knowledge_file244、knowledge_library33、knowledge_space37，全部实际目标不存在。相关持久账本不等于可直接删除授权；需明确后续清理和 FGA 对账方案。
- 当前模型登记中 model→server 的父行缺失/跨租户错配数为0；tenant13的问题来自助手配置引用另一子租户的有效模型，不是该 model 的自身归属应纠正。

完整字段清单 `structural-diagnostics.json` SHA256：`db4acf9d9da5242b41dd3deb11030226824d168a289d845f6eb7ed922394f747`。详情日志 `logs/tenant-diagnostic-preflight-details.log` 保留实际来源 key、slot、目标物理事实和异常，所有原检查仍抛出，没有诊断异常转为正式 ready。

**第二版归档时的停点（12:29）**：Catalog198、授权模型发布7、write_fenced=false；本次正式 run 仍为0行，没有 M2冻结/M3转换/M4签证。空模型兼容补丁已持久挂载、原两条授权只读预检通过；API、Worker、OCR Worker 继续停止。42条旧模型配置清空请求等待用户决定，其余新增问题未获执行性处置结论，均保留原状。


### 剩余阻塞的只读全字段备份

`remaining-preflight/` 共保存 **4,902 行**诊断及相关上下文，业务修改为0：knowledgefile112、tag170、resource_permission_mode329（328个孤儿模式及1个有效空间3426上下文）、permission_grant656、permission_grant_assignee403、permission_visible_source_projection405、permission_projection_operation521、permission_projection_tuple2304、knowledge1、assistant1，TagLink为0。不能把这4,902行统称为“允许删除的失效数据”；其中包含真实文件、有效空间和完整历史投影审计上下文。

备份包括完整原行 JSON、实际表结构、带明确碰撞拒绝的 INSERT 恢复文本及 manifest/checksums。rows.json SHA256 为 `6acb02d0873917f4554022c238e8a66b93ca037cf80bd7a617d55432b9272a78`；持久服务器副本的4个文件校验通过。未执行恢复、未运行额外 tuple 清理，也不把这份限定 SQL 证据称为完整 OpenFGA Store 或环境恢复点。

新增归档命名 `f118-20261111-v2.tar.gz`，同时包含原3,241行失效关联备份、42条旧模型配置备份、本节剩余证据、实际镜像原源码/兼容补丁/提交补丁/测试结果摘要及完整操作日志。原兼容前 `f118-20261111.tar.gz` 保持不可变。


## 42 条模型配置获批后的执行与续检（2026-11-11 13:30 后）

用户明确确认“备份后清空失效 model 配置并继续”。运行已准备脚本的显式 apply，事务内逐字核对 42 条 live 完整记录与原 `legacy-embedding/rows.json`，确认文件仍为0、本次尚无 frozen run 后，只将 model 设为 NULL，保留 update_time 及其他字段。实际修改42行，42个知识资源全部保留，无文件、Grant、Source、索引或对象存储删除/修改，也未选择替代 embedding。提交后再次查询确认42行均存在且 model=NULL。

执行日志 `logs/legacy-embedding-apply.log`；授权及结果补记 `legacy-embedding/apply-result.json`。原备份 manifest 中 mutation_authorized=false 表示备份当时状态，原文件不改写；此次补充授权与 apply 由新结果文件单独记录。

继续执行原 `_tenant` 全租户只读预检，24个租户通过诊断子步骤，tenant1/13/18/20/25/60仍受阻。此次不是重新启动耗时的正式全 Store 扫描，而是先利用相同原子步骤将剩余问题确认完整；不创建基线、不写 artifact、不冒充 M2 成功。

### 新的实际阻塞：旧 ES/Milvus 结构

tenant1 在 `PhysicalInventoryReader._index → _physical_batch` 报 `migration_inventory_incompatible_physical_identifiers`。进一步只读检查全部 **2,404** 个 type0/3资源，发现 **143 个资源**引用了不兼容旧索引，均属tenant1、SQL knowledgefile数均为0。此错误并非名称格式不符合要求，而是原索引缺少新检索/过滤合同要求的标识字段或其类型不兼容。

实际去重后，涉及 **74 个 Milvus 集合、26 个 ES 索引**；其中 **70 个 Milvus 集合和15个ES索引含数据**。143个资源中有139个引用非空Milvus集合，同一集合可被多个库引用，不能把143理解为143个独立集合。样例：knowledge5 的 `col_1690604122_5de852ba` 有555行，knowledge9的 `col_1690795313_f3a03667` 有145行；schema字段为 source/text/pk/vector，缺少 document_id 和 knowledge_id。

当前检查要求 Milvus 的 document_id/knowledge_id 为 INT32/INT64、text为VARCHAR；ES要求相应 metadata 字段为整数。没有将旧 schema 的兼容标志伪造为true。SQL无文件不能证明物理索引无数据；本轮**没有删除、清空、重建或写入任何旧索引**。

证据：`physical-index-diagnostics.json` 保存原资源索引名、原schema/mapping、计数及摘要，SHA256 `9aad80140310572b3eca2bdc1902a2c03f74d2b0d6c871794e1182543273c5fb`；它是结构证据，不是向量内容备份。日志 `logs/physical-index-diagnostics.log`。

### 文件层级与权限父边的进一步分类

原112条异常文件中，**103条没有对应的 resource_permission_mode**，不能凭父库默认值伪造原文件权限意图。其余9条业务路径与SQL CURRENT父链一致，仅level不符；原FGA读取保留 `condition:null`。最初诊断的字典全等比较将该空字段视作差异，已在原始tuple不变的前提下规范化比较并保留旧诊断版本。

规范化后的准确结果：**8条有额外FGA父边**（89564、93027、94277、96154、96207、96287、96301、97252），各有1条额外边且包含SQL所指向的正确边；**1条97402只有唯一且正确的父边**。没有直接删除那8条额外边，因为它们可能影响当前有效授权集合，需结合原移动态账和来源处理。

对97402，仅纠正层级计数 `1→0`：knowledge_id=3377、file_level_path为空、SQL mode10193 parent为knowledge_space3377、原FGA唯一父边相同。完整原行与 `remaining-preflight/rows.json` 精确比对通过，事务内锁定文件和mode，再以 HIGHER_CONSISTENCY 重读FGA父边。更新后逐字段确认只有level改变，update_time保持。真实父位置、文件内容、Grant/Source、FGA均未变。日志 `logs/verified-depth-counter-repair.log`；这是从三份一致事实恢复计数，不是重新放置文件或授予权限。

`file-hierarchy-plan.json` 保存112条原诊断分类，规范化版SHA256 `7a464bb65c9bcc185d12d67db9f52791ec8a616974a5609b51869fac4cc16a34`；旧版本单独保留。当前原112条异常中还剩111条未修复（103缺模式、8有父边漂移）。tenant25的问题仍在这8条范围内，不能将97402的修复称为tenant25已通过。

### 曾准备、后撤回且未执行：143 个库的索引绑定切换

可回退方案：只修改这143个库的 `index_name/collection_name`，切到逐库独立的新标识 `f118_k{knowledge_id}_20261111`；不在维护脚本中创建索引，不调用embedding，也不修改原ES/Milvus集合或其中任何数据。新标识既未被任何knowledge绑定，也已用原原生客户端确认不存在物理索引。后续有合法模型并上传文件时使用新的索引，原索引继续按旧名称保留。

**可观察影响**：这143个库会解除与旧索引的绑定，之后不再通过这些库读取旧索引；SQL中的文件记录本来均为0。原绑定可按映射恢复，旧物理数据仍在。该变化超出用户刚批准的“只清空42条model”范围，**尚未切换**，需要用户决定是否采用；若要求原绑定也不变，则需另行制定旧结构转换/隔离兼容方案，不能忽略格式检查继续发布。

已生成 `legacy-index-plan/`：143条knowledge全字段原行、实际schema、逐库旧/新索引映射、带新值前提的绑定恢复SQL、manifest及SHA256SUMS；服务器持久副本6个文件校验通过。rows.json SHA256 `4402a50bca728868ee4ee6187f64795b3ba35f3c039cd2004efa017bcb0e85f8`，plan.json SHA256 `7542fe5021f2738d64aecc270c92657a21ba2cbcb8cdcf223cbd5a98e8d0874b`。

`bisheng116_legacy_index_plan.py --prepare` 未执行任何SQL或物理索引修改；实际切换入口需要独立显式参数，并将再次精确核对原行、确认143个库仍无文件、尚无frozen run及新名称不存在。该步骤只解决旧索引绑定阻塞，其他已记录的文件/授权/跨租户来源/孤儿元数据问题仍需处理，不能承诺切换后整套升级立即成功。

用户随后询问“索引标识是什么意思？”，这不是切换授权。已解释为 knowledge.index_name / collection_name 对应的 ES 索引名和 Milvus 集合名，改变它们会改变知识库查询的数据位置；旧索引实体及数据保留，143库的新绑定方案继续保持未执行。


## 用户指出原技术方案约束后的纠正：撤回索引切换建议

用户追问“为什么需要修改这个？技术方案里不是说不修改milvus和es的数据吗？”。重新核对已确认合同：spec AC-57要求保留索引位置；design §7.2（第525行）明确列出原 collection_name、index_name 不改，第528行要求已有索引不改物理位置，并证明原 file/document 标识能正确解读。

此前提出的“修改SQL绑定、保留物理索引”虽不写ES/Milvus数据，但会断开库与原索引的关联，仍偏离了已确认的升级方案，不能当作本次升级的默认修复。**现已撤回该建议；143个库的索引绑定从未执行切换，所有旧index_name/collection_name和物理索引保持原样。** 用户关于术语和技术方案的追问不是授权。

当前已证实的根因是预检 `_milvus_compatible/_es_compatible` 对原 schema 的要求：缺少或类型不符的 document_id / knowledge_id 被拒绝；样例旧集合只有 source/text/pk/vector。这个事实说明“原结构未满足当前校验”，不等于F118必须更换索引，也尚不能断言校验应无条件放宽。后续须沿保留原绑定的合同核查旧结构如何解释、是否存在可证明的兼容映射，或更早版本的索引转换前置条件未满足；不能把切换空索引或强制兼容标志当作迁移成功。

原准备方案和备份作为历史证据保留，新增 decision.json 标记withdrawn，准备脚本的apply入口已禁用以免误执行。不修改spec/design以追认该偏差，不改写旧索引，不跳过物理完整性检查。42条model清空及97402仅level计数修正是此前已执行事项，均与索引绑定切换无关。

## 原索引保留和跨租户失效增量（2026-11-11 后续）

用户明确拒绝换空索引并要求原技术方案继续；另确认原助手 `e029e59bda05450aaf82ac11d252c3a7` 的模型800配置保留为跨租户失效，不共享、不复制、不新增权限，运行/发布继续拒绝。相应 AC-93 窄例外、design、QA 与发布合同已同步。14 个生产文件兼容补丁：仅对没有 SQL 文件或目录的原资源冻结可核对的索引保留证明，原 physical identifier_compatible=false 及 schema/count/绑定仍如实保留；M3 和续跑之前核对所有相关租户实时零文件集与原绑定。旧模型槽位登记真实 target_tenant_id，并单列 invalid_scope_count；同步/异步 Owner 仅允许原槽位保留/移除，详情返回失效，运行、发布、预览与新增/复制继续拒绝。

本地组合回归 2,041 passed / 1 failed；失败是频道配额加载角色策略触发 no-network，在改动前基线也单项复现。最终关键选集 72 passed；含原索引 SQL 转换/续跑、文件/目录/绑定漂移拒绝和真实 M2/M3/M4 跨租户失效覆盖闭合。代码审查见 `f118-preserve-index-and-invalid-scope-20261111.md`；Ruff、架构 guard 与 diff-check 通过。现场原 13 个文件与本次基线完全匹配，新增物理保留证明模块原不存在，原件及最终候选哈希保存于 `preserve-index-and-scope-fix-v2/`。

进一步核对已备份的 103 条缺 mode 文件：全部是 Root 租户 space_upload 的 FAILED 文件，仍有非空对象名及非零文件大小；102 条在知识资源3494下引用已不存在的目录90829，另1条在3490下引用已不存在的89614。上传失败或缺权限元数据不能当作文件可删除证据；本次未删这些记录、未清对象文件、未重建目录或凭空补授权。其他 8 条层级计数错误同时有 FGA 多 parent，328 条资源已不存在的权限 mode 及关联、170 条无容器且无 TagLink 的标签、现有空间3426的授权适用范围闸门仍需处理。保留完整诊断及行级备份，未绕过检查。

### 本轮现场验证及未完成状态（14:44–15:00，+08:00）

- 修复提交 `54a66afa7f9212bffe0e8d05eb330b73795285ca`，合入本地发布线 `aac80d7fe1`。已保留发布线期间其他人的提交和主工作区所有无关未提交文件；没有推送。
- 新维护容器 `bisheng-test-permission-upgrade-v3` 使用原镜像加只读 19 个文件挂载（原权限兼容5个 + 本次14个），所有新挂载哈希逐一匹配提交代码。宿主机 override 原件另存 `preserve-index-and-scope-fix-v2/docker-compose.override.before.yml`。三个业务容器仍停止、未重建；这些挂载对它们仍是待重建生效配置，不声称业务已加载。
- `logs/preserved-original-indexes-live.log`：通过实际补丁 M2 `_physical_batch` 对143个库生成143条零托管文件保留证明，实时SQL绑定以及原ES/Milvus schema/count事实全部逐字段相同。SQL和物理索引写入均为0；结果为 `retention-live-validation.json`，不是正式M2冻结。
- `logs/approved-invalid-scope-live.log`：实际助手原 `model_name=800` 保留；真实模型存在，模型和服务商都归租户18。租户13转换决策为 `existing_invalid_scope`、`exists=true`，租户13整租户只读预检通过。正式引用回填尚未执行，不把诊断记录冒充已完成的M4标记。
- `logs/tenant-preflight-preserved-index-scope.log`：30租户中25通过。当前首个阻塞为 Root 创建者缺失、tenant18现有空间scope闸门、tenant20孤立标签、tenant25文件层级、tenant60失效权限容器。原其余完整性错误仍保留，不凭首个错误覆盖掉既知问题。
- 新暴露的9条均是**既有type3空空间**，ID1479/1480/1483/1484/1485/1486/1487/1490/1501，创建者ID没有实际User，均无SQL文件。没有把它们改为Root管理员或生成创建者授权。全行、schema、恢复SQL及哈希写入 `missing-creator-evidence/`；SHA256校验全部OK，rows哈希 `67f9c44e755ecfd8aad82a824c84aef40c6be41424be5be34260da74358e07ab`。
- `remaining-native-details.json`：103条父目录丢失的失败文件及目录89614/90829，在当前原模型下HIGHER_CONSISTENCY读取均为0条tuple，不能据此创造父目录或继承授权。空间3426则有既存ACTIVE可见来源9763、授权14827、来源19883，不能按失效元数据删除；其模型等级2的证据与授权范围继续保留。
- 待核实清理候选逐条ID清单 `remaining-metadata-candidate-scope.json`：mode328、Grant653、assignee399、visible source401、tag170，共1951行，均已包括在原 `remaining-preflight/rows.json` 全量证据中。排除有效mode7592及空间3426的全部有效上下文；投影Operation/Tuple历史不在候选删除范围内。完整下游及FGA核验尚待执行，这不是无条件删除许可。

本轮没有新增SQL/FGA业务数据写入或物理存储修改。仍为 Catalog198/Authorization7，正式run `116-f118-20261111` 无冻结行，无本轮M3/M4，无权限CURRENT发布，升级**未完成**。原空模型的user747/user745两项HIGHER_CONSISTENCY可见检查继续保留。剩余“历史结构失效保留”合同和已删除目标元数据清理已分别向用户发出补充确认，在取得答复前不实施依赖它们的变更。完整本轮材料以新版本包v4归档，不覆盖v1/v2/v3。

## 第二轮授权、精确清理与结构兼容（2026-11-11）

用户明确批准AC-100–102范围及备份核实后清理170标签/328已删除资源mode关联。旧v4 pending状态是确认前历史快照，不能据此忽略本轮授权。原142,855条FGA tuple重新完整只读扫描，原物理对象与全部SQL有效下游逐项核验；328目标均全局不存在，170标签均无TagLink，其中部分标签的父ID在其他租户存在，实际分类为“原租户无有效父容器”，而非全局都已删除。其他租户空间保留。原始父事实记录于approved-metadata-cleanup/tag-parent-facts.json。

最新备份目录approved-metadata-cleanup包含精确1,951完整行、1,952原tuple及8处有效修复上下文，全体SHA256校验OK；原SQL全字段/DDL/恢复SQL仍在remaining-preflight，原rows hash不变。当前选集rows SHA256为d7915b00945359d241734d1354a1f24404a892b7df50afb4e6044dc9fff11922。清理只删除mode328、Grant653、assignee399、visible source401、tag170；历史ProjectionOperation/Tuple未删除。

经原生ProjectionService.prepare→mark_projecting→execute→HIGHER_CONSISTENCY确认，新增336个审计操作2777–3112全部FINALIZED，删除1,952个已备份FGA键（包括8个已证实多余父边）；没有FGA WRITE。最后原生SQL事务重新锁定并比较原行/目录/有效下游，删除上述1,951行并仅修正8个file.level计数。原file_level_path及有效mode父关系均未移动，103失败文件和所有对象/ES/Milvus保留；有效8个mode只按原生投影协议推进版本/operation指针。结果时间15:49:24+08:00，日志logs/approved-metadata-cleanup-apply.log，完整operation IDs见approved-metadata-cleanup/apply-result.json。

结构兼容新增封闭计划证据及全图闭合验证，首次/续跑于任何租户业务写入前原生重验。对103失败文件没有权限初始化，存在已保存直接引用时仍拒绝；保留原行，按通常迁移登记V1元数据不产生可见性。空间3426需要证明的原因是原模型在该类型上动作为空，但已有真实ACTIVE可见来源与等级2；新纯可见标记只能保留原效果。无ACTIVE原证据或等级变化仍阻断。

本地新增27项（含M2/M3/M4及续跑）通过，另99项选集通过；扩展选集1,786 passed、1 failed，为已在修改前复现的频道配额/角色策略no-network基线失败。最后补充“其他来源借用失联创建者”和“直接引用失效文件”两项拒绝测试。正式现场升级/发布/服务恢复结果将继续追加；本段不声称已完成升级。


## 第二轮预检续办：27/30后新增的三处兼容问题

v4维护容器已加载AC-100–102，30租户逐项预检27通过。剩余实际记录：①Root空间3495的文档1703/2705，4个版本对应文件88520/88519/89520/89522全部FAILED，原主指针NULL、全部is_primary=0；不选择主版本、不改原链，只保留已有type3的此类原失败状态。②租户25工作流1d63b332d55849e189b2aade9efda872，版本4442，node:rag_fa801.knowledge引用Root空间3603「验证性能」，原is_shared=0；沿用保留配置、跨租户失效、不新增权限原则，保留真实owner=1，不视为Root共享或目标缺失。③租户60应用b9cde779b7144b91b3184b1f3b700e3c的mode10949中，原21064/21065/21066都是RETIRED来源历史，旧Grant仍INACTIVE，assignee4220529232719530634已改绑且INACTIVE；迁移错误地要求全部历史行对应当前Grant/model。保留历史，以原主体/来源指纹和旧INACTIVE Grant闭合重建，不恢复有效授权。

完整原行/DDL/恢复SQL/manifest已持久保存并SHA256核验：primary-chain-evidence（2文档、4版本、4文件、1空间）、next-blockers-evidence（原工作流/版本/目标空间及24Grant、2assignee、4可见来源、mode1，原引用表当时0）。后者rows SHA256 b993f49fbce8d259db29ce1636b1a6f4f9a437f63bda4b88b5c666b5c0ff12dd。本段没有新SQL/FGA业务修复，也没有改动原索引或文件，正式升级/访问恢复仍待后续执行和核验。


tenant60首处通过后又定位到同类mode10954/app ac03e3f7a34c4a16a1d7bf2cdfc395a2：21068为RETIRED，assignee1932647580758220349已从模型6f06…改绑viewer、版本1→2且保持ACTIVE；旧Grant18105因其他用户组仍使用而ACTIVE。兼容必须保留退役贡献，而不要求整个Grant/来源都停用。补充完整备份next-blockers-evidence-v2：2mode、48Grant、5assignee、8可见来源及原工作流/目标，rows SHA256 f511dcea95599598ad00d96e87cb072deccee8e27f1e5a4bdc7faf91ff46689c，宿主机全校验通过；无SQL清理。

扩展选集1995 passed / 3 failed：一项旧预检仍期望外租户空间立即阻断，已按同一失效保留合同修订为existing_invalid_scope并保留名称解析拒绝；另两项实际尝试本机未初始化MySQL连接，分别为legacy_document_permissions的混合原类型列表，以及已知deleted_channel配额策略no-network问题。补充原生锁顺序/Owner/M4选集63 passed，历史贡献及纯规划85 passed；最终现场验证仍另记。

# F118 聊天历史确认项与当前脚本核对

日期：2026-11-13。基线：最新远端 `origin/feat/3.1.0-beta1` / `0b78bd7acc`。隔离工作树：`codex/f118-migration-scope-audit-20261113`。

核对依据为本聊天中用户后续确认的规则；较早的保留方案、旧 spec、旧测试和116现场处置不能覆盖后续决定。本文独立核对生产调用链及回归用例，不把此前报告写过“已实现”作为实现证据。

本轮没有登录服务器、执行迁移、恢复服务或修改业务数据。下文“代码已接入”表示正式入口存在对应处理及回归定位，不表示真实 MySQL/DM8、对象/向量库和完整业务验收全部通过。

## 结论与本轮需要纠正的口径

- 此前发现的 G1–G10、R1–R4 修复已在最新 beta1 的实际代码中，不再只是116现场操作。主要入口为 `prepare_f118_history.py`、`unify_knowledge_spaces.py`、M2/M3/M4、权限发布及正式维护恢复 CLI。
- 第14项在审计基线中有明确缺口：未换空索引，但 M2 仍强制读取 ES/Milvus 存在性、schema/count，读取失败阻断迁移。此前评为“已按收敛执行”不完整。本轮已解除新Run的全量物理依赖，使用独立bindings_only策略；旧Run原证据和孤儿精确清理保留。
- 审计基线中新 Run 默认预览仅列出租户，不能称为全量dry-run。本轮已接入正式M2同路径的完整只读扫描、临时分页图校验及退出清理；preflight_complete不代表正式READY，同名Run被并发冻结时拒绝。
- 原 Run 已完成后新增租户引起的集合不一致，是历史 Run 复核范围问题，不能通过删租户、补造旧 Run 行或改写原冻结基线处理。新扫描应依据当前业务清单；真正旧库升级复演仍需要未迁移快照。
- 角色跨租户业务方案和 OpenFGA 镜像索引是用户交给其他 agent 的独立事项，不能计为本迁移脚本遗漏，也不能在 F118 中擅自更改角色适用语义。

本轮主修复行为和统一验证见[收敛修复记录](f118-migration-scope-fix-20261113.md)，查询顺序及转换见[完整流程图](f118-migration-current-flow-20261113.md)。以下标明发现前状态的位置为审计发现，不代表修复后仍在调用。

## 37项最新决定逐项核对

表内实现路径省略 `src/backend/bisheng/` 前缀，`scripts/` 位于 `src/backend/` 下。回归文件简称位于 `src/backend/test/knowledge_unification/`；以 `test/` 开头的其他目录同样相对 backend。未在本轮重新执行的用例只列为可核查的已有覆盖。

| 编号 | 最新确认规则 | 正式实现位置与核对结果 | 回归定位 / 范围 |
| --- | --- | --- | --- |
| 1 | 数据转换、新权限模型/Catalog发布及引用覆盖完成后正式开服 | `scripts/unify_knowledge_spaces.py:arun` 串接 M2、M3/M4 和 `production_coverage_factory(...).arequire_global_ready()`；preview 的固定 `ready=false` 不是开服证明 | `test_migration_cli.py`、`test_migration_coverage_production.py`；运维开服和真实业务验收不由脚本 HTTP 健康替代 |
| 2 | 新模型未发布时允许维护旧 CURRENT 对应操作，不回灌旧业务快照 | `scripts/f048_maintenance_runtime.py` 只读 CURRENT pin，禁 Store/model bootstrap；recover/reconcile 已用该维护组合，不先过新版业务准入 | `test_maintenance_current_pin.py`、`test/permission/test_f048_failed_closed_recovery_cli.py`、`test/permission/test_f048_projection_reconcile_cli.py` |
| 3 | 创建失败补偿/恢复不得覆盖后续撤权或新操作 | `permission/application/control_state.py:_owner_fence/finalize_owner/mark_owner_compensation` 校验原幂等键、operation、版本、scope、tenant、pin；CURRENT Grant 不重新激活 | `test/permission/test_f048_recovery_intent_fences.py` 的三个迟到回调拒绝用例 |
| 4 | 其他持久投影恢复遵守相同防回退原则 | `permission/application/sql_runtime.py:SqlProjectionFinalizer.finalize` 在原 mode operation/version 围栏内处理原账本拥有的 FAILED_CLOSED Grant；系统巡检只续办原 bootstrap，跳过 CURRENT | `test/permission/test_f048_recovery_intent_fences.py`、`test/permission/test_f048_system_resource_repair.py`；不据此宣称全平台已有新的后台自动调度器 |
| 5 | 父知识库不存在的文件，备份后清理 SQL 与对应存储 | `scripts/f118_history_business.py:build` 识别缺父库；从原库或精确持久删除清单找原绑定；`OrphanPayloads.capture/apply` 备份并精确清理文件内容 | `test_history_business_repairs.py:test_missing_library_requires_original_binding_evidence`；无可靠原绑定、有效引用或不明下游仍报告，禁止猜删 |
| 6 | 文件 tenant 纠正为真实父资源 tenant，相关关系保持一致 | `f118_history_business.py:build` 生成 `parent_tenant`、已登记目标 tenant、同父 Tag/TagLink 更新；权限 Owner 冲突阻断 | `test_history_business_repairs.py:test_parent_owner_corrections_and_unmapped_embedding_are_selected_backed_and_replayable`、`test_file_tenant_repair_keeps_tag_and_link_owners_consistent` |
| 7 | 只清无有效依据的文档/版本关联，保留有效 knowledgefile | `f118_history_business.py:build` 检查 document、version、file、真实父库；有有效版本但主版本需要人工决定时阻断，不猜选主版本 | `test_history_business_repairs.py:test_orphan_metadata_cleanup_keeps_valid_files_and_replays_same_plan` |
| 8 | TagLink 无有效资源关联，备份后清理 | 同一 business 准备计划核对 Tag/文件两端，编译 `invalid_tag_or_file` 删除，apply 同原计划重验 | 同上孤儿元数据用例；清理不等于普通 TagLink 的9→8类型转换 |
| 9 | 父空间不存在的成员关联，确认后删除 | business 准备只为 `business_type=space` 且父库缺失的 `space_channel_member` 生成删除；不删除用户 | 同上孤儿元数据用例 |
| 10 | 旧空权限模型依据当前状态兼容，不强行改成新授权 | `permission/migration/f118_plan.py` 支持既有规范空定义及当前有效来源；首次 F048 writer 与在线 writer 身份分别识别 | `test_legacy_empty_model_compat.py`、`test_legacy_empty_model_sql_runtime.py` |
| 11 | 以当前业务数据和当前来源迁移，不恢复早期 F048 快照 | `f118_plan.py` 验当前 CURRENT 原事实及两种来源协议；`unification_sources.py` 从当前保存配置提取 | `test_legacy_empty_model_compat.py:test_actual_f048_writer_identity_is_preserved_without_recanonicalizing_sources` 等；writer 格式识别不是要求旧业务内容不变 |
| 12 | 保留空动作模型及既有可见语义 | `f118_plan.py` 与空模型/可见来源编译器保留原定义和既有贡献；不补具体动作或新主体 | `test_legacy_empty_model_compat.py` 的既有可见贡献、最后贡献撤销及禁止新授权用例 |
| 13 | 无可靠映射的旧 embedding，备份后清 NULL | business 准备仅对0/1/3类资源的非数字旧名称，在无文件/QA登记、无切换且当前/旧配置均无名称映射时生成 `unmapped_legacy_embedding` | `test_history_business_repairs.py` 的归属/模型修正及 `test_empty_embedding_cleanup_does_not_clear_invalid_ids_or_nonempty_qa`；助手名称不套用此规则 |
| 14 | SQL 与底层向量不一致暂缓，保留索引绑定和数据 | 基线仍强制物理盘点；本轮已移除CLI向量客户端装配和M2物理批次，新图写bindings_only、旧图保留原合同 | `test_migration_binding_policy.py`、`test_migration_inventory_application.py`、`test_migration_cli.py`；不因SQL-only策略绕过孤儿精确清理 |
| 15 | 已保存助手跨 tenant 模型配置保留，由用户界面修复 | 业务模型目标读取支持精确原槽位的 `invalid_scope`，保留真实 Owner；新增/复制、执行/发布/预览仍拒绝 | `test_preserved_foreign_model.py`；不得共享、复制或猜绑模型 |
| 16 | 已有空空间缺创建者，保留 user_id | `unification_structural_retention.py` 保存 creator retention；不补账号、成员或权限；普通库转换不借用该例外 | `test_migration_structural_retention.py` 的空空间创建者保留、漂移拒绝及新转换拒绝 |
| 17 | 缺父目录的孤儿文件备份后清存储，FAILED本身不构成删除依据 | 新准备计划识别真实缺父链、有效下游和引用；新 M2 要求先清理，不再新建旧 stranded retention；旧冻结 Run 继续按原材料读 | `test_history_business_repairs.py:test_orphan_file_physical_failure_keeps_sql_and_original_plan`、`test_history_physical.py`；只删除原文件 ID 内容，不 drop 索引/集合 |
| 18 | 修复覆盖/重试隐式改目录；历史 level、多父边按当前父链修正 | `LegacyRetryApplication` 拒绝 parent_changed；当前重复上传保留原目录；history `valid_chain/capture/apply` 修 level，原正确父边存在时删除额外边 | `test_prepare_history.py`、`test_legacy_upload_overrides.py`、`test_legacy_space_retry.py`；有效链不明则阻断 |
| 19 | 无有效关联的失效 Tag 备份后删除 | business 准备核对容器和剩余链接；原容器不存在且没有有效下游才删本体 | `test_history_business_repairs.py` 孤儿元数据用例 |
| 20 | 清已删目标的 mode 与派生授权，保留操作审计 | history `hard_missing/mirrors/downstream` 加 `DeletedResourceCleanup` 精确清 mode/Grant/assignee/visible_source 及其 FGA 派生 | `test_prepare_history.py` 的叶子到父树清理、下游漂移、SQL失败续跑；历史逻辑删除需原删除回执，不把普通实体存在误判为硬删除 |
| 21 | 已确认三条失效 UserRole 可清；后续不扩成 F118 全角色治理 | 三条属于116历史执行事项；新 M2 不读取 Role/UserRole 作为无关完整性门槛 | 按第31项收敛；本轮不重新清角色、不改变适用语义 |
| 22 | FAILED 是正常文件状态，不能因此删文件或强设主版本 | business 孤儿判断使用父链/引用，未以 status 决定清理；M2保留合法全失败无主链形状 | `test_migration_structural_retention.py:test_new_m2_requires_orphan_cleanup_independent_of_parse_status` 等 |
| 23 | 工作流已有跨 tenant 空间引用保留失效，后续用户维护 | 精确已有槽位保留原 ID/真实归属、登记失效；执行与新槽位读取仍拒绝 | `test_preserved_foreign_space.py`、`test_wf_bindings.py` |
| 24 | 正常删除清派生数据，审计保留 | Flow、Assistant、Channel、App、Tool、Dashboard 的现有 RESOURCE_DELETE 事务提交后均调用 adapter.cleanup_deleted；知识删除保留原接线 | `test_app_lifecycle.py`、`test_wf_root_entry.py`、`test/permission/test_f048_dashboard_permissions.py`、`test/tool/test_f048_tool_permissions.py` 等；无全平台历史后台垃圾回收承诺 |
| 25 | 已下线旧 flow 技能不参与；真实工作流的旧版本仍处理 | `unification_inventory_repository.py` 按真实父 Flow.flow_type 排除1类旧技能，其子版本1/10/NULL均排除；父10的旧版本仍处理 | `test_migration_inventory_repository.py:test_retired_skill_parent_is_excluded_regardless_of_child_type` |
| 26 | 已删除版本保留，但不注册有效引用 | 来源盘点冻结 retired/deleted_parent 原来源，M4清退有效登记；不恢复已删除目标 | `test_migration_invalid_workflow_history.py`、`test_migration_source_lifecycle.py` |
| 27 | 版本 tenant 统一修正到真实父工作流 | business 准备生成 `parent_workflow_tenant`；已有外租户独立权限或来源登记时阻断；新 M2 检查准备已完成 | `test_history_business_repairs.py` 的父归属修正；不再把新错归属版本默认登记 foreign_parent 原值保留 |
| 28 | 助手旧模型名称原样保留，由用户明确选模型修复 | `unification_sources.py` 与助手提取器登记旧名称失效配置；知识引用继续登记；新建/复制不支持旧名称，不自动落默认模型 | `test_migration_legacy_assistant_name.py` 覆盖保留、手动 ID 修复、运行拒绝及知识删除保护 |
| 29 | 无生效贡献的旧 Grant 模型缺失按历史保留 | `f118_plan.py` 对 INACTIVE 且无生效来源贡献的缺模型 Grant惰性保留；真实生效贡献缺模型仍阻断 | `test_migration_legacy_assistant_name.py:test_inert_missing_model_definition_survives_full_native_m2_m3_m4` |
| 30 | 历史未生效授权和可见语义保持 | 空模型/可见来源计划保留 INACTIVE 与零效果；不因迁移自动激活授权 | `test_legacy_empty_model_compat.py`、`test_legacy_empty_model_sql_runtime.py` |
| 31 | 收敛角色盘点，不借迁移改变全局角色含义 | `unification_preflight.py` 新 M2 不调用 Role/UserRole 盘点；旧 codec 可读旧材料 | `test_migration_space_membership_global.py`、`test_migration_broker_application.py` 对收敛后的行为；跨 tenant 角色登录问题由独立方案处理 |
| 32 | 修复 Root 先到、Source 头跨页后到的分页问题 | `unification_inventory.py` 的 pending_creators/source_headers 按完整精确来源头延迟闭合，未借用其他 root 的证据 | `test_migration_legacy_assistant_name.py:test_missing_creator_retention_waits_for_actual_header_across_the_199_record_boundary` |
| 33 | 不检查 Celery 消费/队列，停全服务由运维保证 | 新 M2 不调用 broker/queue reader，旧 task 页只保留解码；SQL删除 prepared/deleting 半态仍是业务完整性检查 | `test_migration_broker_application.py`、`test_migration_source_lifecycle.py`；不能把业务 tombstone 检查误写成 Celery 检查 |
| 34 | 已有等价目标 namespace 父边复用，旧边退役 | `f118_permission_tuples.py:finish` 仅凭精确原 SQL/目标转换计划闭合复用，未知目标边拒绝 | `test_permission_publication_edges.py` 的 duplicate_parent 与无精确证明拒绝用例 |
| 35 | 按当前业务/授权来源分类 extra，不泛化认领 | `f118_permission_tuples.py` 新策略移除已证明的额外父/模式边，保留明确旧共享/系统形状，来源不明授权阻断；旧 frozen 策略继续可读 | `test_permission_publication_edges.py` 的 extra_parent、unknown graph、旧冻结策略用例 |
| 36 | 死资源不补 marker，活资源按当前事实恢复必要 marker | raw inventory 批量读真实业务存活及最后 operation 状态；权限计划冻结 restore_missing_markers；最后删除未提交、操作未收尾阻断 | `test_permission_publication_edges.py` 活资源恢复/死资源不复活；`test_migration_inventory_repository.py` 真实存活；不是仅凭 CURRENT mode 即补标记 |
| 37 | 产出 OpenFGA 索引修改与 read_tuples 评估交接 | `docs/reviews/openfga-mysql-read-index-handoff-20261112.md` 说明查询形态与索引；BiSheng 迁移仍通过原 pin 读取权限图 | 文档交付与外部镜像索引实施分开；本轮不宣称对方镜像已构建/部署 |

## 37项之后的补充确认

| 后续确认 | 代码与验证依据 | 结论 |
| --- | --- | --- |
| 已删除工作流旧版本不能阻断 | 正常工作流软删除保留主行并标记版本；旧历史缺父/已删版本按 retired 来源处理。`test/workflow/test_flow_soft_delete.py` 与 `test_migration_invalid_workflow_history.py` | 代码已接入；未对所有现场历史版本重新扫描 |
| 频道 `new-folder-*` 遗留配置跳过，用户手动重绑 | `channel/domain/services/reference_extractor.py` 仅识别完整 `new-folder-[0-9]{1,20}`；M2跳过该 folder target、保留配置与空间引用并记录 warning；投递拒绝该失效绑定 | `test_migration_legacy_channel_folder.py` 覆盖正式 M2→M4及续跑、原配置不改、正常空间权限继续检查 |
| 前端保存目录不能把占位字符串传给后端 | **实际在 client SPA**：`pages/Subscription/Article/useAddToKnowledge.ts` 创建完成前禁确认，处理器二次拒绝占位值，使用 createFolderApi 返回的真实 ID；关闭重开旧响应无效 | `AddToKnowledgeModal.environment.test.tsx`、目录选择相关用例已有覆盖；本轮只读核对，未重跑浏览器 |
| 配额预检 MySQL 排序规则修复 | `role/domain/repositories/quota_repository.py` 订阅关联采用 `StrJoinKey(parent.id)`；`core/database/dialect_helpers.py` MySQL 显式 `COLLATE utf8mb4_unicode_ci`，其他方言普通CAST | `test/quota/test_subscription_count_collation.py`，只编译验证不等于真实 MySQL 执行 |
| 旧全局角色绑定导致登录10609交独立 agent评审 | 本轮 F118 不复制角色、不改绑定关系、不改变跨租户角色适用策略；已有方案交接文档与代码迁移解耦 | 有意独立处理，不能标为本轮迁移脚本自动修好 |
| 最新 release 现场验证只能跑脚本，阻塞记录即停，不挂代码 | 本轮仅本地源码/测试；此前116记录仅证明当时镜像和已完成 Run 复核状态 | 不把本轮代码修复写成已部署，不重置116或109 |

## 本轮独立验证与剩余边界

1. 已逐项追踪 history capture/apply、精确物理清理、M2来源/权限/业务盘点、M3/M4、CURRENT pin维护组合、操作围栏、正常删除后的清理调用点、频道 client 保存逻辑和配额实际查询。
2. 八个与本次复核直接相关的后端专项文件在统一禁网环境执行，**98 passed、2 skipped，15.18秒**。两项为本机不可用的 DM8 方言依赖检查，不代表 DM8 执行通过；SQLite 使用真实事务，存储使用测试替身，没有调用生产中间件。原有 SQLModel 等警告仍计入结果，未当作零告警。
3. 父库已失且无原绑定、共享对象、无法按 file ID 定位的旧向量 schema、有效引用/未知下游、有效权限 Owner 冲突、主版本歧义等继续报告。这些是无法证明可安全处置的范围，不应以“所有历史数据都自动修”隐藏。
4. 第3/4项的已有恢复入口已补防回退，不能据此宣称任意后台任务都会自动恢复；第33项没有要求在迁移中盘点或管理队列，本轮不扩成新的调度功能。
5. 既有软删除历史派生数据与硬删除缺失不同：能依据原删除回执续办；不以一张存活实体表或残留 CURRENT mode推断所有历史操作已完整清理。正常删除接线不等于全平台后台垃圾回收。
6. 第37项的查询是 OpenFGA 权限关系读取，和本轮要移出的 ES/Milvus 文档/向量统计是不同系统、不同用途，不能一起删除。

本轮不声称37项全部完成现场验收；应以本轮修复、测试证据、后续固定镜像验证和独立事项交付分别判断。

本轮专项命令（工作目录 `src/backend`）：

```bash
config=/private/tmp/f118-scope-audit-tests.yaml PYTHONPATH=/private/tmp:. \
  /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  -p f118_scope_no_network \
  test/knowledge_unification/test_history_business_repairs.py \
  test/knowledge_unification/test_history_physical.py \
  test/knowledge_unification/test_prepare_history.py \
  test/permission/test_f048_recovery_intent_fences.py \
  test/quota/test_subscription_count_collation.py \
  test/knowledge_unification/test_migration_legacy_channel_folder.py \
  test/knowledge_unification/test_migration_legacy_assistant_name.py \
  test/knowledge_unification/test_migration_structural_retention.py \
  -q --disable-warnings --show-capture=no
```

日志：`/private/tmp/f118-history-confirmations-audit-20261113-final.log`；JUnit：`/private/tmp/f118-history-confirmations-audit-20261113-final.xml`。主修复修改 inventory 的中间态曾出现同一字段尚未接齐的首轮失败；接口完成后本轮按上述命令重新执行并通过，不把中间态失败误报为现场数据问题。

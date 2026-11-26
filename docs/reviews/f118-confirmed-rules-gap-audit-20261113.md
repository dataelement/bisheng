# F118已确认规则落实核查

> 这是修复前核查快照。修复后的规则、流程、验证和限制见[落实记录](f118-confirmed-rules-implementation-20261113.md)。

日期：2026-11-13。核查基线：`feat/3.1.0-beta1` / `aa8b75f8441d9a1b08300afc21e25a913d32bec5`。已fetch核对，该时点本地HEAD与远端一致；相关脚本/知识迁移/权限源码无未提交修改。

以本聊天中用户**后续确认的最新规则**为准，较早的spec、116临时处置及旧测试不能覆盖后续决定。承接[逐项反馈](f118-migration-feedback-and-flow-20261112.md)、[后续确认记录](f118-recovery-and-open-questions-20261112.md)及[当前流程图](f118-migration-data-flow-20261113.md)。

本轮只核查及本地隔离复现，没有修改生产逻辑、登录服务器、清理数据或执行升级。本文不声称发现的所有形状都存在于109/116现状。

## 1. 结论

确认有**10类迁移准备/转换规则没有完整落地**，见G1–G10；另有恢复配套R1–R3未收口，正常删除接线R4尚非全平台覆盖。

主要是两类问题：

- 116现场做过清理或改归属，但通用脚本只实现了权限派生清理和level修复，没有业务孤儿治理及归属修正。
- 用户后来已把“保留”改为“清理/纠正”，或把宽泛保留改为按当前业务事实分类，但代码、spec和测试仍验证较早策略。

此前“122项通过”是当时选定代码回归通过，不能用来证明这37项最新决定均已实现。核查发现spec仍有AC-101孤儿失败文件保留、AC-107错租户版本原值保留，二者均与用户后续明确决定冲突。

## 2. 尚未完整落地的迁移规则

| 编号 | 原反馈编号 | 最新已确认规则 | 当前实现及影响 |
| --- | --- | --- | --- |
| G1 | 5、17 | 父库不存在，或父目录已删且确认没有有效下游的孤儿文件，备份后清理SQL及对应MinIO/ES/Milvus文件内容 | prepare把坏父链列blocked；M2还保留旧的“103类失败文件失效保留”分支。没有本轮所需的孤儿物理清理计划；有的形状阻断，有的仍按旧规则保留 |
| G2 | 7及此前清理授权 | 无有效文件/父库/文档依据的文档与版本关联，备份后清理；有效knowledgefile保留 | prepare仅检查文件/文档父链和level，不清文档/版本孤儿；M2继续在document_parent_invalid、version_parent_invalid或primary链检查阻断。109文档50属于已实际遇到的入口 |
| G3 | 8、19 | 无有效资源的TagLink，及无有效关联/下游的失效Tag，备份后清理 | prepare没有Tag/TagLink删除计划；M2仍拦tag_parent_invalid、tag_file_parent_invalid、tag_container_missing等。只做9→8转换/等价重复绑定去重，不等于失效关系清理 |
| G4 | 9 | 父空间确实不存在的成员关联，备份后删除，不删用户 | prepare没有space_channel_member孤儿清理；M2全局成员父资源检查仍报global_parent_invalid |
| G5 | 6 | 文件归属统一纠正为真实父资源tenant，连带关系正确维护 | prepare仅对错tenant父链报invalid_parent_chain；M2在file_parent_invalid阻断。正式SQL命令未修KnowledgeFile.tenant_id；116的43条是现场操作 |
| G6 | 27 | 工作流版本归属异常时，备份并按真实父流程修正tenant，维护来源登记 | 仍用foreign_parent失效来源保留原行，不改tenant；旧测试明确要求M4及续跑前后FlowVersion整行相同。4757的新决定没有替换早期保留方案 |
| G7 | 13 | 已核实无可靠映射的旧embedding名称，备份后清空model，保留资源/索引/权限 | 42条仅在116现场清空；prepare没有该计划。Knowledge提取器仍把model按数字ID解析，旧非数字名称抛knowledge_model_configuration_invalid；与“助手旧名称保留由用户修复”是不同规则 |
| G8 | 35 | 当前业务结构和有效授权决定父边/授权；已证明失效派生残留备份清，不明关系报告 | 已硬删除目标的权限purge已实现；但未移动namespace节点上的schema合法extra键仍可宽泛保留，不要求其有当前有效业务/Grant来源。后续确认的分类收紧未完整实现 |
| G9 | 36 | 已删除资源不补技术marker；活资源依当前模式、有效授权和操作状态恢复所需marker | 编译器对permission_enabled/custom_mode/inherit_mode统一要求原图已存在才保留；没有在迁移链中按活资源状态恢复缺失marker。已删除资源不复活这一半已实现，活资源恢复这一半未实现 |
| G10 | 25 | 已下线旧flow技能不参与当前工作流迁移，以真实父领域为准 | 常见父type1/版本type1已排除；父type1但版本type10或NULL仍被查询纳入，再报workflow_parent_invalid。已在SQLite真实ORM查询复现，不是仅推测 |

### G1/G2：业务孤儿清理与权限purge是两种能力

当前`prepare_f118_history.py`计划只有levels、parents、purges。purges装的是mode及其Grant/assignee/visible_source和FGA键，**不删除knowledgefile、knowledge_document或knowledge_document_version**。

即使把prepare的blocked改成continue，M2仍有独立的父库、版本、标签、成员完整性检查，所以不能靠降低报错级别实现“清理后跳过”。应在新M2冻结前按已确认规则形成独立备份/清理计划，完成后才盘点。

文件有真实有效归属时，只清错误文档/版本关系；不能因一条断裂文档关系连带删除有效文件。孤儿文件的物理清理须定位原对象/切片，保留共享集合、索引本体及其他有效文件。此前“不修改ES/Milvus”的保留原则，不应被解释为忽略后来明确批准的孤儿文件内容清理。

代码证据：[历史prepare的capture/apply](../../src/backend/scripts/prepare_f118_history.py)、[M2文档/版本/文件检查](../../src/backend/bisheng/knowledge/domain/repositories/unification_resource_repository.py#L628)、[旧失败文件保留分支](../../src/backend/bisheng/knowledge/application/unification_structural_retention.py#L80)。

### G3/G4：不能把转换或权限清理当业务关联清理

TagLink 9→8和等价重复绑定去重是转换规则；没有有效目标的TagLink、失去父容器的Tag，以及父空间删除后的成员行，是不同清理对象。当前prepare没有这些对象的备份/清理命令。

代码证据：[标签转换及容器缺失拒绝](../../src/backend/bisheng/knowledge/application/unification_conversion_plan.py#L313)、[TagLink全局完整性](../../src/backend/bisheng/knowledge/domain/repositories/unification_resource_repository.py#L710)、[成员父空间完整性](../../src/backend/bisheng/knowledge/domain/repositories/unification_space_membership_repository.py#L303)。

### G5/G6：归属修正尚未成为通用命令

正式SQL转换命令只有ResourceConversion、InitializeV1、TagConversion、TagLinkConversion、DefaultConversion，没有文件/工作流版本tenant纠正命令。prepare也没有这两类修正。

G6仍保留[foreign_parent记录](../../src/backend/bisheng/knowledge/application/unification_workflow_retention.py#L12)，对应[版本读取分支](../../src/backend/bisheng/knowledge/domain/repositories/unification_inventory_repository.py#L310)。旧[原行不变测试](../../src/backend/test/knowledge_unification/test_migration_invalid_workflow_history.py#L84)会通过，但不是最新“按父流程纠正tenant”规则通过。

后续修复应在备份、锁定和有效关系检查后纠正归属并维护依赖；已经冻结或完成的Run不能因此重写原baseline/plan。存在真实有效授权冲突时仍需报告，不能用改tenant静默扩大访问。

### G7：Knowledge旧embedding与助手旧模型名称不能合并

[Knowledge模型提取器](../../src/backend/bisheng/knowledge/domain/services/model_reference_extractor.py#L19)直接调用canonical_target_id；NULL无引用，非数字旧名称失败。当前助手的旧名称保留机制不覆盖这个Knowledge配置字段。新的通用清空规则也应限定于已核实无可靠映射的旧embedding配置，不推广为清空所有失效模型ID或助手配置。

### G8/G9：旧版保留策略仍被测试固化

- [tuple builder](../../src/backend/bisheng/permission/application/f118_permission_tuples.py#L203)只要端点未迁移、两schema允许且关系形状合法，就可保留extra；当前有效来源分类收紧尚未落地。
- [marker编译过滤](../../src/backend/bisheng/permission/application/f118_permission_tuples.py#L87)统一以before中是否存在技术键决定生成，无活资源恢复分支。
- [原生测试](../../src/backend/test/knowledge_unification/test_permission_publication_edges.py#L373)仍分别验证“缺marker保持缺失”和“额外旧父边保持存在”。

这与用户后来确认的“分类处理失效派生、恢复活资源所需marker”不完全一致。不能把最早临时保留政策或特殊抽检通过当作后续规则已落实；也不能反过来补齐所有marker使已删除资源复活。

### G10：已下线旧技能排除不完整

[版本查询](../../src/backend/bisheng/knowledge/domain/repositories/unification_inventory_repository.py#L310)使用OR条件纳入父类型10、版本类型10或版本类型NULL；check随后要求父类型10。因此真实父已明确是旧技能type1时，部分子标签仍会触发阻断。

本地隔离查询结果：父type1/子type1返回0条；父type1/子type10、父type1/子NULL均返回`unification_inventory_workflow_parent_invalid`。只需以真实父领域排除已废弃技能，不能同时忽略真实type10工作流下的旧type1保存版本。

## 3. 恢复配套与正常删除链的剩余范围

| 编号 | 原反馈 | 已有部分 | 尚缺部分与证据 |
| --- | --- | --- | --- |
| R1 | 2 | 域投影服务已有固定Store/model的原操作恢复能力，现场也据此完成过恢复 | 正式recover/reconcile入口仍先调用新版`ensure_runtime_ready`/业务runtime，没有公共旧CURRENT pin维护组合。[recover](../../src/backend/scripts/recover_f048_failed_closed_projection.py#L136)、[reconcile](../../src/backend/scripts/reconcile_f048_projection_operations.py#L159) |
| R2 | 3、4 | 已有原操作围栏、BEFORE/AFTER核验及部分业务resume | 通用finalizer仍只挑`PermissionGrant.projection_state=PROJECTING`推进PENDING；创建补偿改成FAILED_CLOSED的Grant仍被漏选。内置技能等状态恢复与调度未统一。[finalizer](../../src/backend/bisheng/permission/application/sql_runtime.py#L723) |
| R3 | 3、4 | 迟到`fail_closed`已加原operation/版本约束；STAGE逆补偿已重验围栏 | `finalize_owner`仍按Grant ID推进ACTIVE，`mark_owner_compensation`仍有按资源更新mode/Grant的分支，未统一按原operation/版本收尾。不能宣称旧恢复绝不覆盖新意图已验收。[owner收尾/补偿](../../src/backend/bisheng/permission/application/control_state.py#L991) |
| R4 | 20、24 | 历史硬删除目标的通用派生purge已实现；知识删除cutover后已接入清理 | 非知识业务Owner的正常删除尚未全部接入，不能宣称全平台日常删除均清完派生。`DeletedResourceCleanup`业务调用当前集中在knowledge_deletion；这是接线范围边界，不否定历史prepare的通用purge |

R3是已确认的代码校验缺口，本轮没有构造跨进程竞争来证明某个用户的撤权已实际被恢复。原子围栏和普通路径已有保护不能忽略；也不能仅凭两处修复把所有补偿路径都算完成。

## 4. 37项最新决定逐项对照

“已落地”指该规则在当前迁移/关联业务调用链有实现，不代表所有真实中间件和完整业务验收已完成。“不纳入/暂缓”依据后续明确收敛，不计入漏实现。

| 原编号 | 最新规则/问题 | 当前判定 | 依据或缺项 |
| --- | --- | --- | --- |
| 1 | 数据转换、模型发布、覆盖完成才能开服 | 已落地 | 正式CLI、M3/M4及全局Coverage准入；运行健康不能替代 |
| 2 | 新模型发布前允许受控旧模型维护恢复 | 未完整落地 | R1 |
| 3 | 创建补偿/自动恢复且不能回退新意图 | 部分 | R2/R3，不能宣称统一收口 |
| 4 | 其他持久投影恢复遵守相同规则 | 部分 | R1/R2/R3；已有业务resume和原操作围栏保留 |
| 5 | 父库不存在的文件与存储清理 | 未落地 | G1 |
| 6 | 文件tenant按父资源纠正 | 未落地 | G5 |
| 7 | 文档/版本关联及有效文件保留边界 | 解释已有，通用清理缺失 | G2 |
| 8 | 无有效资源的TagLink备份清理 | 未落地 | G3 |
| 9 | 已删除空间成员备份清理 | 未落地 | G4 |
| 10 | 旧空模型按当前状态兼容 | 已落地 | f118_plan的当前Catalog/来源协议处理 |
| 11 | 识别旧writer格式，以当前事实迁移 | 已落地 | 首次F048/在线writer协议识别；不回灌旧快照 |
| 12 | 保留空动作模型及原可见性 | 已落地 | 空动作/visibility-only计划及共享runtime来源读取 |
| 13 | 无可靠映射的旧embedding备份清NULL | 仅116现场执行 | G7；助手名称保留是另一条规则 |
| 14 | SQL与底层索引不一致暂缓治理 | 已按收敛执行 | 原绑定/物理事实保留，不换空索引；不要求此轮治理 |
| 15 | 原助手跨tenant模型配置保留，用户修复 | 已落地 | existing_invalid_scope、原槽位编辑与运行拒绝 |
| 16 | 缺创建者的既有空空间保留user_id | 已落地 | creator_retention；不补账号/成员/授权，不适用于普通库新转换 |
| 17 | 缺旧目录的孤儿文件清理物理内容 | 与最新决定相反 | G1；仍保留stranded_retention/旧AC-101 |
| 18 | 覆盖重试bug与历史level/多父修复 | 已落地限定修复 | process_retry_files拒绝改父；prepare按有效父链修level，正确FGA父边已在才删额外边。G8宽保留问题仍另列 |
| 19 | 无有效关联的失效Tag备份删除 | 未落地 | G3 |
| 20 | 已删目标的mode及派生权限清理 | 已落地，在线范围有限 | prepare/DeletedResourceCleanup；R4边界 |
| 21 | 3条失效角色关联清理 | 现场已做，后续不纳入F118 | 按31收敛，不要求F118继续治理全部Role/UserRole |
| 22 | FAILED是正常状态，不据此删文件/强选主版本 | 已落地 | 既有全失败无主链保留；G1仅按孤儿身份处理，不按FAILED删 |
| 23 | 工作流旧跨tenant空间引用保留失效 | 已落地 | 原ID与owner保留，原槽位可修复，运行拒绝 |
| 24 | 清派生数据，保留真正操作审计 | 已落地，在线范围有限 | 历史purge及知识删除接线；R4，不删除operation/tuple审计 |
| 25 | 不处理下线旧flow技能，真实工作流旧版本仍提取 | 部分 | 常见分支已做；G10旧技能子标签10/NULL仍阻断 |
| 26 | 已删除版本保留，不注册有效引用 | 已落地 | deleted_parent退役来源及M4对账 |
| 27 | 版本tenant纠正为父工作流tenant | 与最新决定相反 | G6；仍是foreign_parent原值保留/旧AC-107 |
| 28 | 旧名称助手留配置，用户界面明确改模型 | 已落地 | 旧名称失效标记、知识引用保护、明确ID修复；不猜默认 |
| 29 | 无生效贡献的旧Grant模型缺失按历史保留 | 已落地 | 惰性Grant快照，不重建模型；有ACTIVE贡献仍阻断 |
| 30 | 原未生效授权与可见语义按历史保留 | 已落地 | 保留INACTIVE/零效果，不因visibility-only激活 |
| 31 | F118不改变全局角色适用语义，收敛盘点 | 已落地 | 新M2不调用Role/UserRole盘点；旧冻结codec继续可读 |
| 32 | 修复Root先到Source头后到的分页bug | 已落地 | 精确来源头延迟闭合；逐Root核对，不借用创建者豁免 |
| 33 | 迁移不检查Celery消费，停服务由运维保证 | 已落地 | 新M2不调用broker/队列盘点；SQL业务删除半态检查仍在 |
| 34 | 等价目标namespace父边复用，退役旧边 | 已落地 | 精确旧SQL/目标计划闭合后复用，无重复写；陌生目标仍阻断 |
| 35 | 当前有效业务/授权分类处理extra键 | 部分，仍用旧宽保留 | G8 |
| 36 | 死资源不补marker、活资源按当前状态恢复 | 部分 | G9，仅不补死资源这半已实现 |
| 37 | OpenFGA索引与read_tuples评估交接 | 文档交付已做，外部实施不纳入本脚本 | 已有OpenFGA交接文档；另一个agent的镜像实施未在本轮验收 |

## 5. 本轮验证证据与边界

1. 静态追踪正式CLI→history capture/apply、M2→M3→M4、权限tuple builder及recover/reconcile入口，核对实际写入命令和调用方；没有仅凭“文件名存在”认定实现。
2. 禁止网络的本地纯函数/SQLite真实ORM构造：Knowledge旧非数字embedding名称返回`knowledge_model_configuration_invalid`，NULL为0引用；父type1旧技能的子type1被排除，子type10/NULL仍报父域错误。
3. 原生迁移回归选集6 passed、4.84秒：缺父目录文件保留、错tenant版本原行不变、缺marker保留、额外旧父关系保留。**这些测试通过证明旧行为仍存在，不能当作最新规则通过。**
4. 对照最新确认，至少AC-101/107需随修复一起调整；35/36的宽保留测试也需要改成有效来源/生命周期分类的断言，不能只改文档。
5. 本轮没有重跑全部37项E2E；“已落地”是源码/既有证据层面的结论，未声称真实MySQL/DM8全量旧库演练或全部客户端业务通过。

## 6. 建议的收口顺序

先补G1–G5的业务孤儿/关联清理与父归属纠正，避免每次升级遇到一类历史孤儿就停止；再补G6/G7的受控配置/版本修正；同时按最终生命周期规则收紧G8、补齐G9及G10。所有清理沿“预览候选→选中原值备份→重验→显式apply→余量核验”，不嵌入Alembic，不删除有效下游，不改写已冻结Run。

R1–R3作为迁移前恢复能力单独闭环；R4按各Owner真实删除事务逐一接线。文档、spec、测试与产品脚本必须用同一最新版规则验收，116现场执行记录单列，不能再作为“所有环境已可自动升级”的依据。
